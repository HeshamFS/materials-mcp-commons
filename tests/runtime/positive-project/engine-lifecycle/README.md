# Engine lifecycle manifest

`manifest.json` describes the bounded read-only discovery behavior implemented by `LifecycleRegistry.discover`. Its two package schemas define the accepted query/limit input and the compact card result. The manifest is loaded from this exact package root, its schema bytes are checksum-pinned, and every reference resolves from the explicit offline profile/package registry.

This is project control-plane evidence, not a concrete scientific plugin. It has no backend handler, network client, scientific dataset, or numerical output. Dispatch remains outside W-0201.
