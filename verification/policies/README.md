# Verification Runtime Policies

Policies constrain external runtimes independently of repository recipes. They define environment,
provider, network, resource, and cleanup boundaries that recipes cannot broaden.

Policy edits require a dedicated security issue, negative tests, runtime conformance, policy digest
updates, and threat-model review. Adapter construction tests alone do not prove live isolation.
