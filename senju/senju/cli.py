"""
senju.cli — コマンドライン入口。

  python -m senju.cli demo                 短時間デモ（レポートを標準出力）
  python -m senju.cli run [options]        本格的なトーナメント＋レポート保存
  python -m senju.cli safety-check <ref>   スコープ検問の単体テスト

すべての対戦は in-process 仮想標的に対して行われ、実ネットワークを使わない。
"""
from __future__ import annotations

import argparse
import sys

from .config import ArenaConfig, EvolutionConfig, SenjuConfig
from .economy import EconomyConfig
from .report import render_markdown, write_report
from .safety import ScopeGuard, ScopeViolation, experimental_lab_policy
from .tournament import Tournament


def _build_config(args: argparse.Namespace) -> SenjuConfig:
    return SenjuConfig(
        scenario_name=args.scenario,
        arena=ArenaConfig(
            red_action_budget=args.red_budget,
            blue_action_budget=args.blue_budget,
            seed=args.seed,
        ),
        evolution=EvolutionConfig(
            population_size=args.population,
            generations=args.generations,
            matches_per_generation=args.matches,
            seed=args.seed,
        ),
        economy=EconomyConfig.extreme() if getattr(args, "extreme", False) else EconomyConfig(),
        report_dir=args.report_dir,
    )


def _cmd_run(args: argparse.Namespace) -> int:
    config = _build_config(args)
    extra_hosts = list(getattr(args, "allow_host", None) or [])
    guard = ScopeGuard(experimental_lab_policy(hosts=extra_hosts))
    tournament = Tournament(config, guard)
    report = tournament.run()

    path = write_report(report, config.report_dir)
    if not getattr(args, "quiet", False):
        print(render_markdown(report))
        print(f"\n[saved] {path}", file=sys.stderr)
    else:
        print(f"[saved] {path}", file=sys.stderr)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    args.population = 16
    args.generations = 6
    args.matches = 40
    args.scenario = "demo-web"
    args.seed = 42
    return _cmd_run(args)


def _cmd_safety_check(args: argparse.Namespace) -> int:
    guard = ScopeGuard(experimental_lab_policy())
    try:
        guard.check(args.ref)
        print(f"✅ 許可: {args.ref}")
        return 0
    except ScopeViolation as e:
        print(f"⛔ 拒否: {e}")
        return 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="senju", description="Senju 攻防シミュレーション基盤")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--scenario", default="default-web")
        sp.add_argument("--population", type=int, default=24)
        sp.add_argument("--generations", type=int, default=10)
        sp.add_argument("--matches", type=int, default=60)
        sp.add_argument("--red-budget", type=int, default=12)
        sp.add_argument("--blue-budget", type=int, default=12)
        sp.add_argument("--seed", type=int, default=None)
        sp.add_argument("--report-dir", default="reports")
        sp.add_argument("--quiet", action="store_true", help="レポート本文を標準出力しない")
        sp.add_argument("--extreme", action="store_true", help="苛烈な戦争経済プリセット")
        sp.add_argument(
            "--allow-host",
            action="append",
            metavar="HOST",
            help="追加許可ホスト（複数指定可）",
        )

    sp_run = sub.add_parser("run", help="トーナメントを実行しレポート保存")
    add_common(sp_run)
    sp_run.set_defaults(func=_cmd_run)

    sp_demo = sub.add_parser("demo", help="短時間デモ")
    add_common(sp_demo)
    sp_demo.set_defaults(func=_cmd_demo)

    sp_safe = sub.add_parser("safety-check", help="スコープ検問の単体確認")
    sp_safe.add_argument("ref", help="標的参照 (例: sim://x, 8.8.8.8, 10.0.0.1, example.com)")
    sp_safe.set_defaults(func=_cmd_safety_check)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
