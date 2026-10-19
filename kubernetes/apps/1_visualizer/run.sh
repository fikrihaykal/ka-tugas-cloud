# Bind IPv4 localhost. Listener ":22222" becomes IPv6-only on many hosts;
# Firefox on Windows then cannot reach WSL via http://127.0.0.1:22222/.
# setsid keeps Octant alive after the starting shell exits.
setsid ./octant \
	--disable-open-browser \
	--disable-origin-check \
	--listener-addr 127.0.0.1:22222 \
	--accepted-hosts '*' \
	${KUBECONFIG:+--kubeconfig "$KUBECONFIG"} \
	>> octant.nohup.out 2>&1 < /dev/null &
echo $! > octant.pid
