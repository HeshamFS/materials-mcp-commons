# Frozen profile controls

Each manifest in this directory pins every tracked byte in a publicly distributed exact profile directory. The contract suite compares the working tree with this fallback digest set and, when the recorded Git object is available, independently derives the same file inventory and hashes from the publication commit.

Changing both a published schema and this manifest therefore fails the Git-object check in a repository with the publication history. Archive environments without Git still enforce the checked-in digest set.
