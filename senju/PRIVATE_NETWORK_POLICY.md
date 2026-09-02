# Private Network Contact Policy

Private-network reachability is supported as a separate, explicit authority lane next to the normal public `ExternalContactClient`.

## Supported switch

`allow_private_network = true`

This switch is valid only inside a `PrivateNetworkPolicy` that also declares:

- one or more exact hostnames;
- one or more RFC1918 IPv4 or IPv6 ULA CIDRs;
- read-only HTTP methods only (`GET`, `HEAD`, `OPTIONS`).

## Hard boundaries

Private-network contact does **not** inherit broad public external-contact authority.

The private lane rejects:

- wildcard/broad CIDRs such as `0.0.0.0/0`;
- public CIDRs;
- loopback and link-local targets, including metadata endpoints;
- multicast and unspecified addresses;
- hosts outside the exact allowlist;
- resolved addresses outside the configured private CIDRs;
- credential-bearing request headers;
- write/destructive methods (`POST`, `PUT`, `PATCH`, `DELETE`);
- non-default ports;
- redirects unless explicitly enabled, with every hop revalidated.

## Rationale

Public external contact and private-network reachability can both be available to Senju, but one must not implicitly authorize the other. Keeping their authority scopes distinct prevents a public-host grant from becoming an internal-network grant, and prevents a private-network grant from becoming arbitrary internet egress.
