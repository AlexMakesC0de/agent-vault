<div align="center">

<img src="docs/assets/logo.svg" width="88" height="88" alt="Agent Vault のロゴ">

# Agent Vault

**使っているすべてのコーディングエージェントで共有する 1 つのメモリと、プロジェクトごとの個別のメモリ。**

[![Tests](https://github.com/AlexMakesC0de/agent-vault/actions/workflows/tests.yml/badge.svg)](https://github.com/AlexMakesC0de/agent-vault/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-555)
![Claude Code | Codex](https://img.shields.io/badge/works%20with-Claude%20Code%20%7C%20Codex-B4471C)

[English](README.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · **日本語**

これは翻訳版です。内容に違いがある場合は英語版の [README.md](README.md) が正となります。

</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/viewer-dark.png">
    <img src="docs/assets/viewer-light.png" width="860" alt="Agent Vault のメモリページ。SOUL.md、USER.md、MEMORY.md のサイズメーターを備えたプロフィールと、種類、出典、Copy request ボタンを表示した設定カード">
  </picture>
  <br>
  <sub>読み取り専用のメモリページ。ここではデモデータで表示しています。</sub>
</p>

コーディングエージェントはセッションが終わるたびにすべてを忘れ、しかもエージェントごとに独自の形式でメモを残します。Agent Vault は、Claude Code、Codex、そして指示ファイルを読むあらゆるエージェントに**同じメモリ**を提供します。あなたが誰でどう働きたいか、どこでも通用する教訓、そしていま作業しているプロジェクトの事実です。中身はディスク上のただの Markdown で、すべての変更に根拠と履歴が残り、マシンの外には何も出ていきません。

## 目次

- [主な特徴](#主な特徴)
- [仕組み](#仕組み)
- [クイックスタート](#クイックスタート)
- [エージェントにセットアップを任せる](#エージェントにセットアップを任せる)
- [メモリを確認する](#メモリを確認する)
- [よく使うコマンド](#よく使うコマンド)
- [プロジェクトのナレッジ](#プロジェクトのナレッジ)
- [複数のデバイス、チーム、その他のエージェント](#複数のデバイスチームその他のエージェント)
- [よくある質問](#よくある質問)
- [コントリビュート](#コントリビュート)
- [ライセンス](#ライセンス)

## 主な特徴

- **1 つのプロフィールをすべてのエージェントで。** Claude Code と Codex は、フック経由で同じアイデンティティ、設定、汎用的な教訓を読み込みます。その他のエージェントは、それぞれの指示ファイルを通じて同じファイルを使います。
- **プロジェクトごとの vault。** プロジェクトの事実はそのプロジェクトで作業しているときだけ読み込まれるため、あるプロジェクトの詳細が別のプロジェクトに漏れることはありません。チームと共有すると決めない限り、vault はリポジトリの外に置かれます。
- **小さなコアと、リンクされたノート。** 各コアには文字数の上限があり、どのセッションにも収まります。詳細はリンクされたトピックノートに置き、エージェントはタスクで必要になったときだけそれを読みます。
- **根拠と履歴。** 保存される事実にはすべて出典と種類（explicit、observed、inferred）が記録され、変更のたびに以前の値が残ります。古い版にもとづく書き込みは拒否されるので、互いに上書きし合うことはありません。
- **信頼できる振り返り。** エージェントが作業を終える前に、フックが学んだことの振り返りとその記録を求めます。何も変わらなかった場合でもです。
- **検索、診断、ビューアー。** メモリ全体を対象にしたランキング付きの全文検索、読み取り専用のヘルスチェック、そしてすべてを一目で確認できる静的ページがあります。
- **ローカル完結、依存関係なし。** Python 標準ライブラリだけで動きます。サーバーも API キーも、運用するデータベースも不要です。

## 仕組み

メモリは Markdown が入ったいくつかのフォルダーです。マシンごとに一度インストールする小さなルーターが、各エージェントのセッションに何を見せるかを決めます。

```mermaid
flowchart LR
    subgraph agents["あなたのエージェント"]
        CC["Claude Code"]
        CX["Codex"]
        OA["その他のエージェント"]
    end
    subgraph machine["あなたのマシン"]
        R["ルーター<br/><sub>~/.config/agent-memory</sub>"]
        P["agent-profile/<br/><sub>SOUL · USER · MEMORY · ノート</sub>"]
        V1["agent-vaults/shopfront/<br/><sub>MEMORY · ナレッジノート</sub>"]
        V2["agent-vaults/data-pipeline/<br/><sub>MEMORY · ナレッジノート</sub>"]
    end
    CC -- "フック" --> R
    CX -- "フック" --> R
    OA -- "指示ファイル" --> R
    R -- "毎セッション" --> P
    R -- "shopfront で作業中" --> V1
    R -- "data-pipeline で作業中" --> V2
```

プロフィールは常に読み込まれます。プロジェクトの vault は、そのプロジェクト名を出したときかそのフォルダー内で作業したときに読み込まれ、事実はその vault の中にとどまります。学んだことも同じ経路で戻ってきます。

```mermaid
sequenceDiagram
    autonumber
    participant You as あなた
    participant Agent as エージェント
    participant Hooks as Agent Vault のフック
    participant Memory as プロフィールと vault
    You->>Agent: セッションを開始
    Hooks->>Memory: プロフィールとプロジェクトの vault を読む
    Memory-->>Agent: アイデンティティ、設定、教訓、プロジェクトの事実
    You->>Agent: 「ログインのバグを直して」
    Agent->>Agent: 作業し、必要なリンク先ノートを読む
    Agent->>Hooks: 終了しようとする
    Hooks-->>Agent: まず学んだことを振り返って
    Agent->>Memory: 検証済みの事実を根拠付きで保存、または「新情報なし」と記録
    Agent-->>You: 最終回答
```

## クイックスタート

**Python 3.11+**、**Git**、そして Claude Code か Codex（または両方）が必要です。Windows では Git for Windows（Git Bash を含みます）をインストールしてください。WSL は不要です。

**1. Claude の自動メモリをオフにする**（Claude Code ユーザー向け）。これは別のストアで、Agent Vault と競合します。先に[メモを退避してからオフにしてください](docs/claude-auto-memory.md)。

**2. ツールを取得し、プロフィールを作成する。** `agent-vault` と `agent-profile` を置きたいフォルダーで次を実行します。macOS と Linux では `python3` を使い、Claude しか使わない場合は `--codex-hooks` を外してください。

```bash
git clone https://github.com/AlexMakesC0de/agent-vault.git
cd agent-vault
python scripts/agent-memory.py --profile ../agent-profile init-profile
python scripts/project-memory-router.py install --profile ../agent-profile --codex-hooks
```

インストールは既存のクライアント設定を保持し、先にバックアップを取ります。アカウントやリポジトリは一切作成しません。

**3. プロジェクトを追加する。** `--workspace` には既存の Git プロジェクトを指定し、`MyApp` と `myapp` をそのプロジェクト名に置き換えます。

```bash
python scripts/setup-vault.py --vault ../agent-vaults/myapp --name MyApp
python scripts/project-memory-router.py register --id myapp --name MyApp --root ../agent-vaults/myapp --workspace /full/path/to/MyApp
```

プロジェクトのリポジトリは変更されません。プロジェクトごとに繰り返してください。どのプロジェクトも 1 つのプロフィールを共有します。vault の利用をやめるには `project-memory-router.py unregister --id myapp` を実行します。ファイルは残ります。

**4. 確認する。** クライアントを再起動し、確認を求められたらフックを信頼します。新しいチャットで次のように尋ねてください。

> どの中央プロフィールと、どの MyApp プロジェクトメモリを読み込みましたか？それぞれのパスとリビジョンを表示してください。

続いてヘルスチェックを実行します。これは何も変更しません。

```bash
python ~/.config/agent-memory/router.py doctor
```

<details>
<summary><b>各ファイルの置き場所</b></summary>

```text
Your chosen folder/
├── agent-vault/            The tools, cloned from this repository
├── agent-profile/          Your memory, created by init-profile
│   ├── SOUL.md             Who your agent is (one identity for all agents)
│   ├── USER.md             Your preferences
│   ├── MEMORY.md           Lessons that apply across projects
│   └── notes/              Detail too long for the cores, read on demand
├── agent-vaults/
│   └── myapp/
│       ├── MEMORY.md       Facts about MyApp only
│       └── docs/knowledge/ Linked topic notes
└── MyApp/                  Your project; Agent Vault adds nothing to it

~/.config/agent-memory/     Installed router, search index, viewer page
```

</details>

## エージェントにセットアップを任せる

コマンドを打ちたくない場合は、ツールを置く空のフォルダーで、次の文章を Claude Code か Codex に貼り付けてください。

```text
このマシンに Agent Vault（https://github.com/AlexMakesC0de/agent-vault）をセットアップしてください。
README.md を読み、「Quick start」の手順に正確に従ってください。Windows では python、
それ以外では python3 を使ってください。
- 手順 1 の前に、Claude の自動メモリのガイドが何を変更するかを見せ、
  私の了承を待ってください。
- どの Git プロジェクトを追加するか、そのフルパスを私に確認してください。推測しないでください。
- --codex-hooks を付ける前に、私が Codex を使っているか確認してください。
- プロジェクトのリポジトリは一切変更しないでください。
- 最後に router.py doctor を実行し、その出力を見せてください。
```

インストールが済めば、エージェントはすでにメモリの使い方を知っています。インストーラーがクライアントに指示を追加するためです。

## メモリを確認する

```bash
python ~/.config/agent-memory/view.py --open
```

このコマンドは HTML ページを 1 つ `~/.config/agent-memory/view.html` に書き出して開きます。サイズメーター付きのプロフィール、登録済みのすべてのプロジェクト vault、人物に関するノート、最近の変更が表示されます。まだ読み込まれていない推定エントリーは破線の枠で描かれます。

このページは**読み取り専用で、ネットワークから何も読み込みません**。何かを変更したいときは、カードの **Copy request** を押し、そのテキストをエージェントとのチャットに貼り付けてください。エージェントがメモリ CLI を通じて履歴付きで変更します。ページには個人のプロフィールが含まれるため、ビューアーは vault やプロジェクトのフォルダーへの書き出しを拒否します。

## よく使うコマンド

これらを自分で実行することはほとんどありません。エージェントはセッションのコンテキストでこれらを受け取ります。何があるかを知っておくために載せています。

| 内容 | コマンド |
| --- | --- |
| ある情報がどこに記録されているか探す | `python ~/.config/agent-memory/router.py search merge jobs --project myapp` |
| インストールとメモリの状態を確認する | `python ~/.config/agent-memory/router.py doctor --fetch` |
| メモリをページとして表示する | `python ~/.config/agent-memory/view.py --open` |
| セッションで読み込まれる内容を出力する | `python ~/.config/agent-memory/router.py context --prompt MyApp` |
| 登録済みのプロジェクトを一覧表示する | `python ~/.config/agent-memory/router.py list` |
| 事実を保存する（根拠と現在のリビジョンを添えて） | `python ~/.config/agent-memory/agent-memory.py --root PATH update --help` |
| プロジェクトのリンク付きノートを検査する | `python ~/.config/agent-memory/agent-memory.py --root PATH check-knowledge` |

[メモリコマンドの一覧](docs/maintenance.md)

## プロジェクトのナレッジ

プロジェクトの vault は 2 層構成です。`MEMORY.md` は毎セッション読み込まれる小さなコアで、ほぼすべてのタスクに当てはまるルールを置きます。それ以外はすべて `docs/knowledge/` にトピックノートとして置きます。1 ノートに 1 トピックとし、領域ごとのマップの下にまとめ、互いに言及する箇所でリンクします。エージェントはマップから読み始め、タスクに必要なノートだけを開くので、プロジェクトが大きくなってもセッションごとのコストは一定に保たれます。

プロジェクトのノートを作るには、エージェントに **vault-knowledge** スキルを使うよう頼んでください。リポジトリを調べ、マップを書き、ノートを埋め、`check-knowledge` ですべてのリンクを検証します。vault のノートが 5 件未満のときは、セッションのコンテキストがエージェントにこの作業を提案するよう促します。

[Obsidian](https://obsidian.md) は任意です。プロフィールと各 vault をそれぞれ別の Obsidian vault として開くと、リンクをたどって閲覧できます。エージェントは Markdown を直接読むので、Obsidian を起動しておく必要はありません。

## 複数のデバイス、チーム、その他のエージェント

- **別のデバイス。** メモリは自動では同期されません。プロフィールを自分専用のプライベート Git リポジトリに置き、各 vault もそれぞれ独立したリポジトリにしたうえで、[デバイスガイド](docs/devices.md)に従ってください。
- **チーム全体で使う vault。** `setup-vault.py --root /path/to/MyApp --name MyApp` で vault をプロジェクトのリポジトリ内に置き（Codex を使う場合は `--codex-hooks` を追加）、`--workspace` なしで登録します。これによりメモリ用のスクリプト、フック、ノートがリポジトリにコミットされ、クローンした全員がそれらを読み込みます。
- **その他のエージェント。** 指示ファイルを読み、シェルコマンドを実行できるエージェントなら、同じメモリを使えます。そのエージェントのファイルを `install --instructions PATH` に渡してください。
- **古い vault。** 以前のバージョンで生成された `SOUL.md` を持つプロジェクトは、先に[移行](docs/migration.md)が必要です。

## よくある質問

<details>
<summary><b>メモリがマシンの外に出ることはありますか？</b></summary>

いいえ。ツールはローカルのファイルを読み書きするだけで、ツール自身がネットワークリクエストを送ることはありません。唯一の例外は `doctor --fetch` で、ツールキットのクローンに対して `git fetch` を実行します。使っているエージェントは、他の指示ファイルと同じく、渡されたメモリを目にします。そのため秘密情報や顧客データはメモリに入れないでください。
</details>

<details>
<summary><b>なぜコアのサイズに上限があるのですか？</b></summary>

プロフィールと現在のプロジェクトのコアは 1 つのフックメッセージでエージェントに送られ、Claude Code はこのメッセージを 10,000 文字までに制限しています。上限（SOUL 1,500、USER 2,000、MEMORY 2,200）は、両方がその範囲に収まるようにするためのものです。85% に達するとツールが警告するので、保存が拒否される前に詳細をリンク先のノートへ移せます。
</details>

<details>
<summary><b>なぜデータベースではなく Markdown ファイルなのですか？</b></summary>

すべての変更をプルリクエストで読み、差分を取り、レビューできます。ファイルはどのツールよりも長く残り、履歴のチェックもファイルをもとにしています。検索には Markdown から再構築される SQLite インデックスを使うので、インデックスはいつ削除しても安全です。
</details>

<details>
<summary><b>Claude 自身のメモリの代わりになりますか？</b></summary>

はい、信頼できる情報源を 1 つにしたいならそうなります。両者が競合しないよう、[Claude の自動メモリをオフにしてください](docs/claude-auto-memory.md)。`CLAUDE.md` ファイルはこれまでどおり機能します。
</details>

<details>
<summary><b>エージェントが誤った内容を保存したら？</b></summary>

すべての変更でストアの履歴に以前の値が残り、エントリーは無効化されるだけで消去されることはありません。エージェントにエントリーの修正や無効化を頼むか、自分でメモリ CLI を使ってください。
</details>

## ドキュメント

[メモリコマンド](docs/maintenance.md) · [デバイスガイド](docs/devices.md) · [移行](docs/migration.md) · [アーキテクチャと復旧](docs/architecture.md) · [Claude の自動メモリ](docs/claude-auto-memory.md)

## コントリビュート

バグ報告、アイデア、プルリクエストを歓迎します。開発環境のセットアップ、テストスイート、すべての変更が守る少数のルールについては [CONTRIBUTING.md](CONTRIBUTING.md) を読んでください。セキュリティ上の問題を報告する場合は、issue を作成せず [SECURITY.md](SECURITY.md) の手順に従ってください。

## 謝辞

アイデンティティ、ユーザー設定、メモリを分ける構成は [Hermes](https://github.com/NousResearch/hermes-agent) から着想を得ました。上流のコードは一切コピーしていません。

## ライセンス

[MIT](LICENSE)
