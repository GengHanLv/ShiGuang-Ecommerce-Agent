"""生成本地配置，不覆盖已有文件，也不打印密钥。"""

from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / ".env"
    values = (ROOT / ".env.example").read_text(encoding="utf-8")
    for placeholder in [
        "replace-with-random-database-password",
        "replace-with-different-root-password",
        "replace-with-random-storage-password",
        "replace-with-random-application-key",
    ]:
        values = values.replace(placeholder, secrets.token_hex(24))
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(values)
    except FileExistsError:
        print(".env 已存在，保持原样。")
        return
    print("已生成 .env；请填写 OPENAI_API_KEY、模型名和服务商地址。")


if __name__ == "__main__":
    main()
