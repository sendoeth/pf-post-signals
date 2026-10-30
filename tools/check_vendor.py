#!/usr/bin/env python3
"""Step 8: verify the self-hosted chart library against the package npm publishes.

Downloads lightweight-charts@4.2.3 from the npm registry, checks the tarball against the
registry's sha512 integrity value, and compares the vendored file and its LICENSE byte for byte
with the copies inside that tarball. With --install it (re)writes the vendored copy from the
verified tarball. Exit 1 on any mismatch.
"""
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG, VERSION = "lightweight-charts", "4.2.3"
DEST = os.path.join(HERE, "web", "vendor", f"{PKG}-{VERSION}")
FILES = {"package/dist/lightweight-charts.standalone.production.js": "lightweight-charts.standalone.production.js",
         "package/LICENSE": "LICENSE"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pf-post-signals"}), timeout=60) as r:
        return r.read()


def main():
    meta = json.loads(get(f"https://registry.npmjs.org/{PKG}/{VERSION}"))
    tarball = get(meta["dist"]["tarball"])
    algo, want = meta["dist"]["integrity"].split("-", 1)
    got = base64.b64encode(hashlib.new(algo, tarball).digest()).decode()
    print(f"registry {PKG}@{VERSION} tarball {meta['dist']['tarball']}")
    print(f"tarball {algo} integrity: registry {want[:24]}... computed {got[:24]}... -> {'OK' if got == want else 'MISMATCH'}")
    if got != want:
        sys.exit(1)
    fails = 0
    with tarfile.open(fileobj=io.BytesIO(tarball)) as tar:
        for member, name in FILES.items():
            blob = tar.extractfile(member).read()
            path = os.path.join(DEST, name)
            if "--install" in sys.argv:
                os.makedirs(DEST, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(blob)
            with open(path, "rb") as f:
                local = f.read()
            ok = local == blob
            fails += not ok
            print(f"{'OK  ' if ok else 'DIFF'} web/vendor/{PKG}-{VERSION}/{name} sha256 {hashlib.sha256(local).hexdigest()} "
                  f"(package copy {hashlib.sha256(blob).hexdigest()[:16]}...)")
    print("vendored library: " + ("matches the npm package byte for byte" if not fails else f"{fails} file(s) differ"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
