"""从 BAAI 官方模型仓库下载 BGE-M3；首次需要网络和数GB空间。"""

from pathlib import Path
from huggingface_hub import snapshot_download


def main():
    target = Path(__file__).resolve().parents[1] / "Models" / "bge-m3"
    snapshot_download(repo_id="BAAI/bge-m3", local_dir=target)
    print("Embedding model downloaded:", target)


if __name__ == "__main__":
    main()
