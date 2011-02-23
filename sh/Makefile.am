supportdir = $(datadir)/$(PACKAGE)
dist_support_SCRIPTS = \
	inhibitor-functions.sh \
	inhibitor-run.sh  \
	kernel.sh

EXTRA_DIST = early-userspace 

install-exec-hook:
	install -d -m755 $(DESTDIR)/$(datadir)/$(PACKAGE)
	for f in $$(find $(srcdir)/early-userspace -type f); do \
		subdir=$$(readlink -f $$f | sed 's,.*early-userspace/,,'); \
		install -d -m755 $(DESTDIR)/$(datadir)/$(PACKAGE)/early-userspace/$$(dirname $${subdir}); \
		install -m755 $$f $(DESTDIR)/$(datadir)/$(PACKAGE)/early-userspace/$${subdir}; \
	done
	$(LN_S) -f bin/busybox $(DESTDIR)/$(datadir)/$(PACKAGE)/early-userspace/root/init
		
uninstall-local:
	rm -r $(DESTDIR)/$(datadir)/$(PACKAGE)/early-userspace


