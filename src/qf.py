# -*- coding: utf-8 -*-
"""
    CrawlHuabanTdi.qf
    ~~~~~~~~~~~~~~~~~

    Queue function.

    :copyright: (c) 2019 by staugur.
    :license: BSD 3-Clause, see LICENSE for more details.
"""

import os
import time
import shutil
import requests
import json
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from tool import formatSize, makedir, Logger, try_request, rc, diskRate, timestamp_after_timestamp, getDirSize, make_tarfile

logger = Logger("sys").getLogger


def DownloadBoard(downloadDir, uifn, diskLimit=80):
    """
    @param downloadDir str: 画板上层目录，CrawlHuaban插件所在目录，图片直接保存到此目录的`board_id`下
    @param uifnKey: str: 标识索引
    @param site: int: 站点id 1是花瓣网 2是堆糖网
    @param board_id str int: 画板id
    @param uifn: str: 唯一标识文件名
    @param board_pins: list: 画板图片
    @param MAX_BOARD_NUMBER: int: 允许下载的画板数量
    """
    # py3-解码
    downloadDir = downloadDir.encode()
    # 从redis读取数据
    data = rc.hgetall(uifn)
    board_pins = json.loads(data[b"board_pins"])
    CALLBACK_URL = data[b"CALLBACK_URL"]
    MAX_BOARD_NUMBER = int(data[b"MAX_BOARD_NUMBER"])
    board_id = data[b"board_id"]
    site = int(data[b"site"])
    uifnKey = data[b"uifnKey"]
    if len(board_pins) > MAX_BOARD_NUMBER:
        board_pins = board_pins[:MAX_BOARD_NUMBER]
    # 说明文件
    README = set()
    ALLOWDOWN = True
    def writeREADME(_README):
        """更新README提示信息"""
        if _README:
            with open(os.path.join(downloadDir, board_id, 'README.txt'), "a+") as fp:
                fp.write("Error board_id: {}\r\n".format(board_id) + "\r\n".join(list(_README)))
    # 创建下载目录并切换
    makedir(downloadDir)
    # 切换到下载目录
    os.chdir(downloadDir)
    # 创建临时画板目录并创建锁文件
    makedir(board_id)
    if diskRate(downloadDir) > diskLimit:
        ALLOWDOWN = False
        README.add("Disk usage is too high")
    # 初始化请求类
    req = requests.Session()
    req.headers.update({'Referer': 'https://huaban.com/boards/%s' % board_id if site == 1 else 'https://www.duitang.com/album/?id=%s' % board_id, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36'})

    def _download_img(pin, retry=True):
        """ 下载单个图片
        @param pin dict: pin的数据，要求： {'imgUrl': xx, 'imgName': xx}
        @param retry bool: 是否失败重试
        """
        if pin and isinstance(pin, dict) and "imgUrl" in pin and "imgName" in pin and ALLOWDOWN is True:
            imgurl = pin['imgUrl']
            imgname = os.path.join(downloadDir, board_id, pin['imgName'].encode())
            if not os.path.isfile(imgname):
                logger.debug(imgname)
                try:
                    res = req.get(imgurl)
                    if diskRate(downloadDir) > diskLimit:
                        README.add("Disk usage is too high")
                    else:
                        with open(imgname, 'wb') as fp:
                            fp.write(res.content)
                except Exception as e:
                    logger.debug(e)
                    if retry is True:
                        _download_img(pin, False)
    # 并发下载图片
    stime = time.time()
    if ALLOWDOWN is True:
        process = (len(board_pins) / 100) if len(board_pins) > 100 else cpu_count()
        pool = ThreadPool(process)
        data = pool.map(_download_img, board_pins)
        pool.close()
        pool.join()
        logger.info("DownloadBoard over, data len: %s, start make_archive" % len(data))
    # 计算总共下载用时，不包含压缩文件的过程
    dtime = "%.2f" % (time.time() - stime)
    # 将提示信息写入提示文件中
    writeREADME(README)
    # 定义压缩排除
    exclude = [".zip", ".lock", ".tar"]
    # 判断是否有足够的空间可以执行压缩命令，由于压缩时采用了写入立即删除源文件的策略，此处判断可暂时忽略
    # diskRate(d, "all")["available"] > getDirSize(uifn, exclude)
    # 开始压缩目录
    zipfilepath = make_tarfile(uifn, board_id, exclude)
    logger.info("DownloadBoard make_archive over, path is %s" % zipfilepath)
    # 检测压缩文件大小
    size = formatSize(os.path.getsize(uifn))
    # 删除临时画板目录
    shutil.rmtree(board_id)
    # 回调
    try:
        resp = try_request(CALLBACK_URL, timeout=5, params=dict(Action="FIRST_STATUS"), data=dict(uifn=uifn, uifnKey=uifnKey, size=size, dtime=dtime))
    except Exception as e:
        logger.error(e, exc_info=True)
    else:
        if resp and isinstance(resp, dict) and resp.get("code") != 0:
            try_request(CALLBACK_URL, timeout=5, params=dict(Action="FIRST_STATUS"), data=dict(uifn=uifn, uifnKey=uifnKey, size=size, dtime=dtime))
    finally:
        logger.info("DownloadBoard callback is over: %s" % resp)
