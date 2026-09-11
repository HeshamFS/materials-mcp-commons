# Actual engine-control package for Profile 0.1.0

This package declares the discovery and inspection behaviors implemented by this engine against the exact Profile 0.1.0 contracts. Its package schemas are the same engine-owned schemas used by the current Profile 0.2.0 declaration; only the profile manifest contract, profile version, and version-local structured-error reference differ.

It is a real control-plane package, not a scientific plugin or scientific-validation case. The migration suite compares it with the current Profile 0.2.0 package and does not execute either package's implementation code.
