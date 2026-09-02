"""senju.targets.base — 標的・攻撃面・脆弱性クラス・アーキタイプの抽象定義。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


# 攻撃対象となりうる脆弱性クラス（AppSecの標準的カテゴリ）。
# 実コード/実ペイロードは持たない。攻防の抽象モデルとしてのラベル。
VULN_CLASSES: tuple[str, ...] = (
    "sqli",           # SQLインジェクション
    "nosqli",         # NoSQLインジェクション
    "xss",            # クロスサイトスクリプティング
    "csrf",           # クロスサイトリクエストフォージェリ
    "auth_bypass",    # 認証回避
    "jwt_weak",       # トークン(JWT)の脆弱な検証
    "idor",           # 権限のない直接オブジェクト参照
    "priv_esc",       # 権限昇格
    "ssrf",           # サーバサイドリクエストフォージェリ
    "rce",            # リモートコード実行
    "path_trav",      # パストラバーサル
    "deserial",       # 危険なデシリアライズ
    "xxe",            # XML外部エンティティ
    "ssti",           # サーバサイドテンプレートインジェクション
    "race_condition", # 競合状態
    "secrets_exposure", # 秘密情報の露出
    "misconfig",      # 設定不備
    "prompt_injection",         # プロンプトインジェクション
    "tool_misuse",              # ツール・エージェント権限の誤用
    "model_poisoning",          # モデル・コンテキスト汚染
    "insecure_output_handling", # 出力検証不備
    "agent_priv_esc",           # エージェント権限昇格
)


# 標的アーキタイプ = 脆弱性クラス別の「出やすさ」重み。
# 実運用で守る対象の種類に応じて攻防の分布を変える。
ARCHETYPES: dict[str, dict[str, float]] = {
    "web_app": {
        "sqli": 1.4, "xss": 1.6, "csrf": 1.3, "idor": 1.2, "auth_bypass": 1.1,
        "path_trav": 1.0, "ssti": 1.1, "misconfig": 1.0,
    },
    "api": {
        "idor": 1.7, "auth_bypass": 1.4, "jwt_weak": 1.6, "priv_esc": 1.3,
        "nosqli": 1.3, "ssrf": 1.2, "race_condition": 1.2, "misconfig": 1.1,
    },
    "auth_service": {
        "auth_bypass": 1.9, "jwt_weak": 1.8, "priv_esc": 1.5, "secrets_exposure": 1.4,
        "race_condition": 1.2, "misconfig": 1.1,
    },
    "cloud": {
        "ssrf": 1.8, "secrets_exposure": 1.7, "misconfig": 1.9, "priv_esc": 1.5,
        "rce": 1.2, "deserial": 1.1,
    },
    "iot": {
        "rce": 1.7, "path_trav": 1.4, "misconfig": 1.6, "auth_bypass": 1.3,
        "secrets_exposure": 1.2, "deserial": 1.2,
    },
    "ai_agent_cluster": {
        "prompt_injection": 2.0, "tool_misuse": 1.9, "agent_priv_esc": 1.8,
        "insecure_output_handling": 1.6, "secrets_exposure": 1.5, "ssrf": 1.4,
        "model_poisoning": 1.3, "misconfig": 1.2,
    },
    "cloud_native": {
        "misconfig": 1.9, "secrets_exposure": 1.8, "ssrf": 1.7, "priv_esc": 1.6,
        "rce": 1.3, "auth_bypass": 1.4, "jwt_weak": 1.3,
    },
}


def archetype_weight(archetype: str, vuln_class: str) -> float:
    """アーキタイプにおける脆弱性クラスの出やすさ重み（既定1.0）。"""
    return ARCHETYPES.get(archetype, {}).get(vuln_class, 1.0)


@dataclass
class Surface:
    """標的の攻撃面。1つの脆弱性クラスと難易度を持つ。"""

    name: str
    vuln_class: str
    difficulty: float   # 0.0(容易) .. 1.0(困難)
    mitigated: bool = False   # ブルーが対策済みか
    monitored: bool = False   # ブルーが監視下に置いているか


class Target(Protocol):
    """標的インターフェース。"""

    ref: str          # ScopeGuard が検問する参照文字列
    archetype: str    # 標的アーキタイプ

    def surfaces(self) -> list[Surface]: ...

    def reset(self) -> None: ...
