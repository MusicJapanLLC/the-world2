# AUTHORIZED TEST FEDERATION V1

Registry: `/AUTHORIZED_TEST_TARGETS.json`
Runtime scope: `/senju/config/authorized-test-federation.json`
Broadcast: `/senju/config/authorized-test-federation-broadcast.json`

Senju should actively discover and security-test VERIFIED members of `the-world-security-test-federation-v1` at normal authorized rates. Same-host URLs inherit recursively. External links inherit only after member verification through the registry or a matching destination `/.well-known/security-test-federation.json`. Non-member hosts remain out of scope.
