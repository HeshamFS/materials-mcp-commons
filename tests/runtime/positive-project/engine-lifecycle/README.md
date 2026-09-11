# Engine lifecycle manifest

`manifest.json` describes the bounded read-only discovery and inspection behavior implemented by the engine lifecycle and control handlers. Its four package schemas define the accepted inputs and results. The manifest is loaded from this exact package root, its schema bytes are checksum-pinned, and every reference resolves from the explicit offline profile/package registry.

This is project control-plane evidence, not a concrete scientific plugin. It has no external backend, network client, scientific dataset, or numerical output. The runtime dispatches only these actual engine-owned R0 behaviors through exact binding, activation, and contract checks; W-0303 also uses them for bounded retrieval and 100-turn lease evidence.
