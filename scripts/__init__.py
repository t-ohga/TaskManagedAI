"""TaskManagedAI scripts package.

ADR-00021 §3 host-portable deployment CLI entry points を console_script として
公開するため、scripts/ を package 化する。`[project.scripts]` の
`taskhub = "scripts.taskhub_admin:main"` で `taskhub <subcommand>` の起動を
可能にする (Codex R2 F-PR63-003 adopt)。
"""
