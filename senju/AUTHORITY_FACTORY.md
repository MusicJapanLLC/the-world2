# META / X / Senju — Delegated Authority Factory

META・X・Senjuは、必要な用途に合わせて新しいAuthority profileを自律生成できる。

## Core model

```text
SYSTEM root Authority
        ↓ mint
META child Authority
        ↓ mint
X grandchild Authority
        ↓ mint
Senju great-grandchild Authority
```

生成されたAuthorityも `can_delegate=true` かつ delegation depth が残っていれば、さらに子Authorityを生成できる。

この仕組みは **recursive delegation** であり、各世代は独立した `profile_id` / `parent_id` / `issuer` / `generation` / `fingerprint` を持つ。

## Highest-priority invariant

```text
child_authority <= parent_authority
```

Authority生成は「親Authorityの一部を切り出して新しいprofileにする能力」であり、root権限を新しく発明する能力ではない。

子Authorityは以下を親より拡大できない。

- public external-contact hosts
- HTTP methods
- HTTP許可
- redirect許可
- DELETE許可
- request / response byte budget
- timeout
- retries
- rate limit
- credential scope
- Private Network許可
- private hosts
- private CIDRs
- delegation depth

## Who may mint

Authority Factoryのissuerとして認めるのは以下のみ。

```text
META
X
Senju
```

各profileにはissuerが記録される。

## Root Authorities

rootはコードで定義された既存 `ExternalAuthorityScope` から生成される。

初回CLI利用時、registryが存在しなければbuiltin rootが自動seedされる。

例:

```text
root:threat_intel_public
root:github_metadata
root:canary_telemetry
```

## Example 1 — META creates a narrower Authority

```bash
python senju/scripts/authority_mint.py mint \
  --issuer META \
  --parent root:threat_intel_public \
  --purpose "NVD-only research" \
  --hosts services.nvd.nist.gov \
  --methods GET,HEAD \
  --rate 10 \
  --delegate
```

METAはこのprofileを使える。

`--delegate` が付いているため、この新Authority自身もさらに子Authorityを生成できる。

## Example 2 — X creates a grandchild

METAが生成したprofile idが

```text
auth:meta:0123456789abcdef
```

だった場合:

```bash
python senju/scripts/authority_mint.py mint \
  --issuer X \
  --parent auth:meta:0123456789abcdef \
  --purpose "HEAD-only verification" \
  --methods HEAD \
  --rate 4 \
  --delegate
```

生成結果は:

```text
root Authority
  └─ META Authority
       └─ X Authority
```

となる。

## Example 3 — Senju creates another descendant

```bash
python senju/scripts/authority_mint.py mint \
  --issuer Senju \
  --parent auth:x:fedcba9876543210 \
  --purpose "single-purpose observation" \
  --methods HEAD
```

`--delegate` を省略したため、このprofileはterminal Authorityとなる。

## Runtime conversion

生成profileはpublic external laneでは:

```python
profile.to_external_scope()
```

で既存の `ExternalAuthorityScope` に変換できる。

Private Network authorityを親から正当に継承したprofileの場合のみ:

```python
profile.to_private_policy()
```

で `PrivateNetworkPolicy` に変換できる。

Public external authorityだけを持つ親からPrivate Network authorityを新規生成することはできない。

## Persistence

標準registry:

```text
senju/state/delegated_authorities.json
```

各AuthorityはSHA-256 fingerprintを持つ。

保存後にhost・method・rate・credential等を書き換えると、次回load時にfingerprint mismatchで拒否される。

## Why this architecture

このFactoryの目的は、META / X / Senjuが用途ごとに自分でAuthorityを設計し、細分化し、さらにそのAuthorityから次のAuthorityを生成できるようにすること。

固定された巨大なAuthorityを全処理で使い続ける必要がなくなり、AIはタスクごとに小さな能力profileを自律生成できる。

```text
既存Authority
   ↓
用途別Authority
   ↓
さらに用途特化Authority
   ↓
さらに用途特化Authority
```

再帰生成は許可される。

権限昇格は許可されない。
