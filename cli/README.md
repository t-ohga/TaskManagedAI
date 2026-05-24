# TaskManagedAI CLI

`tm` is the project-user CLI for SP-016 UI/CLI parity.

This package intentionally stores no raw operation token in the profile file. Runtime
operation tokens can be supplied through environment variables until keyring/SOPS
storage is wired in a later batch.
