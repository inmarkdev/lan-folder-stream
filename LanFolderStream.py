from pathlib import Path
import queue
import threading
import tarfile

import uvicorn
import zipstream

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse


app = FastAPI()

# ============================================================
# 配置
# ============================================================

SHARE_DIR = Path(r"C:\<dir>")

# 每次传输 4MB
CHUNK_SIZE = 4 * 1024 * 1024


# ============================================================
# 首页
# ============================================================

@app.get("/")
def index():
    return {
        "status": "ok",
        "directory": str(SHARE_DIR),
        "zip": "/d",
        "tar": "/tar",
    }


# ============================================================
# ZIP
# ============================================================

def generate_zip():

    z = zipstream.ZipStream(
        compress_type=zipstream.ZIP_STORED
    )

    # 直接让 zipstream 递归处理目录
    z.add_path(
        SHARE_DIR,
        arcname="SeasunGame",
    )

    buffer = bytearray()

    for chunk in z:

        if not chunk:
            continue

        buffer.extend(chunk)

        if len(buffer) >= CHUNK_SIZE:
            yield bytes(buffer)
            buffer.clear()

    if buffer:
        yield bytes(buffer)


@app.get("/d")
def download_zip():

    if not SHARE_DIR.is_dir():
        raise HTTPException(
            status_code=404,
            detail="SeasunGame 目录不存在",
        )

    return StreamingResponse(
        generate_zip(),
        media_type="application/zip",
        headers={
            "Content-Disposition":
                'attachment; filename="SeasunGame.zip"',
            "Cache-Control": "no-cache",
        },
    )


# ============================================================
# TAR：真正的流式 TAR
# ============================================================

class QueueWriter:
    """
    把 tarfile 写入的数据放进 Queue。
    不在内存中保存整个 TAR。
    """

    def __init__(self, q):
        self.q = q

    def write(self, data):
        if data:
            self.q.put(data)
        return len(data)

    def flush(self):
        pass


def generate_tar():

    q = queue.Queue(maxsize=8)

    END = object()

    error = []

    def create_tar():

        try:
            writer = QueueWriter(q)

            with tarfile.open(
                fileobj=writer,
                mode="w|",
                bufsize=CHUNK_SIZE,
            ) as tar:

                tar.add(
                    SHARE_DIR,
                    arcname="SeasunGame",
                )

        except Exception as e:
            error.append(e)

        finally:
            q.put(END)

    # 后台线程负责读取和生成 TAR
    thread = threading.Thread(
        target=create_tar,
        daemon=True,
    )

    thread.start()

    # 主线程不断把 TAR 数据交给 FastAPI
    while True:

        data = q.get()

        if data is END:
            break

        yield data

    thread.join()

    if error:
        raise error[0]


@app.get("/tar")
def download_tar():

    if not SHARE_DIR.is_dir():
        raise HTTPException(
            status_code=404,
            detail="SeasunGame 目录不存在",
        )

    return StreamingResponse(
        generate_tar(),
        media_type="application/x-tar",
        headers={
            "Content-Disposition":
                'attachment; filename="SeasunGame.tar"',
            "Cache-Control": "no-cache",
        },
    )


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        loop="auto",
        http="auto",
        workers=1,
    )
