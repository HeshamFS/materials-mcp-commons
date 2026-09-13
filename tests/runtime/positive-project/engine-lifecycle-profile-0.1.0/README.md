# Actual engine-control package for Profile 0.1.0

This package declares the discovery and inspection behaviors implemented by this engine against the exact Profile 0.1.0 contracts. Its package schemas are the same engine-owned schemas used by the current Profile 0.2.0 declaration; only the profile manifest contract, profile version, and version-local structured-error reference differ.

It is the real engine control-plane package for this profile. The migration suite compares it with the current Profile 0.2.0 package and does not execute either package's implementation code.
