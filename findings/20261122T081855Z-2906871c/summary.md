# Client network failure, healthy servers

On 2026-11-22, local HTTPS and SSH to 176.12.68.100 timed out after TCP connect. DNS resolved correctly. The academic host was reachable over SSH; both backend and PostgreSQL pairs were healthy, API ports 28081 and 28091 returned 200, and both tunnel services were active. Public HTTPS from the academic host returned 200.

SSH to the VPS succeeded through the academic host. All three edge containers were healthy; memory available 1.4 GiB, root disk 63% used, load 0.07. Locally resolved HTTPS on the VPS returned 200 for /main/, /dev/ and each /api/v1/mailboxes. No gateway log errors appeared in the preceding 30-minute window. Both dev release symlinks remained at ede4f473a794ef7411569e075019c9ae2a57eece; the cancelled fb964f0 deployment had not become current.

The affected client's default route used its VPN tunnel. Binding the same HTTPS requests to its Wi-Fi interface with `curl --interface en0 --connect-timeout 5 --max-time 10` returned 200 for all four endpoints in 32–43 ms (one sample each, not a performance benchmark; evidence attached). Thus this incident does not demonstrate server downtime or a GPU/build regression. The exact failure inside the VPN path was not determined.

With user approval, a local direct-routing exception for the VPS and exact site domains was saved. One initial reconnect was interrupted by user interaction; following the user's instruction not to disconnect the VPN, no further restart was performed. The final domain rule requires the next VPN reconnect, and end-to-end local access with the final configuration remains unverified. Server configuration and application code were not changed. This is a completed diagnosis, not a claim that the pending client routing activation was verified.
