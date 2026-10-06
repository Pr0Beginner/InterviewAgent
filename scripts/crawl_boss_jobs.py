"""低频读取用户可见的 BOSS 岗位，供本地学习和选择器调试。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from backend.app.core.exceptions import ApplicationError
from backend.app.integrations.boss import BossJobSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="读取有限数量的 BOSS 岗位，不绕过登录或安全验证。")
    parser.add_argument("--keyword", action="append", required=True, help="岗位关键词，可重复传入。")
    parser.add_argument("--city", action="append", default=[], help="目标城市，可重复传入。")
    parser.add_argument(
        "--experience",
        choices=("不限", "应届生", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"),
        default="应届生",
        help="工作经验条件，默认应届生。",
    )
    parser.add_argument("--limit", type=int, default=5, help="详情页数量上限，范围 1 到 30。")
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("--limit 必须在 1 到 30 之间")
    return args


async def run(args: argparse.Namespace) -> list[dict]:
    return await BossJobSource().search(
        args.keyword,
        args.limit,
        cities=args.city,
        work_experience=args.experience,
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        jobs = asyncio.run(run(args))
    except ApplicationError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from exc
    print(json.dumps(jobs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
