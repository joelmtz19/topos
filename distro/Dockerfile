# topOS: Debian 12 con topos como forma de ver el sistema.
#   base    el sistema de archivos raíz (sirve tal cual para WSL)
#   live    base + kernel + systemd + live-boot
#   iso     arma el ISO arrancable (BIOS y UEFI) sin privilegios
#   export  sólo el ISO, para `docker build --output`

FROM debian:bookworm-slim AS base
# Inglés por omisión; TOPOS_LANG=es (o LANG=es_MX.UTF-8) lo pasa a español.
# English by default; TOPOS_LANG=es (or LANG=es_MX.UTF-8) switches to Spanish.
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-fusepy fuse libfuse2 sudo bash-completion less nano vim-tiny \
        procps psmisc iproute2 kmod locales ca-certificates \
 && sed -i 's/^# *\(es_MX.UTF-8\)/\1/; s/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen && locale-gen \
 && echo 'LANG=C.UTF-8' > /etc/default/locale \
 && rm -rf /var/lib/apt/lists/*
COPY topos /usr/lib/python3/dist-packages/topos
COPY ejemplos /usr/share/topos/ejemplos
COPY distro/overlay/ /
RUN chmod 755 /usr/local/bin/* \
 && ln -s topos-demo-agents /usr/local/bin/topos-demo-agentes \
 && ln -s topos-service /usr/local/bin/topos-servicio \
 && echo '[ -f /etc/topos/bashrc ] && . /etc/topos/bashrc' | tee -a /etc/skel/.bashrc >> /root/.bashrc \
 && useradd -m -s /bin/bash -G sudo topos \
 && echo 'topos:topos' | chpasswd && echo 'root:topos' | chpasswd \
 && echo 'topos ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/topos && chmod 440 /etc/sudoers.d/topos \
 && chmod 711 /home/topos  && echo user_allow_other >> /etc/fuse.conf  && install -d -m 1777 /var/log/topos  && install -d -o topos -g topos /home/topos/.mundo /home/topos/mundo && python3 -m compileall -q /usr/lib/python3/dist-packages/topos
USER topos
WORKDIR /home/topos
CMD ["bash", "-l"]

FROM base AS live
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        linux-image-amd64 live-boot systemd-sysv dbus \
 && rm -rf /var/lib/apt/lists/* \
 && for unit in getty@tty1 serial-getty@ttyS0; do \
        mkdir -p /etc/systemd/system/$unit.service.d; \
        printf '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin topos --noclear %%I $TERM\n' \
            > /etc/systemd/system/$unit.service.d/autologin.conf; \
    done

FROM debian:bookworm-slim AS iso
RUN apt-get update && apt-get install -y --no-install-recommends \
        squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin grub-common mtools dosfstools \
 && rm -rf /var/lib/apt/lists/*
COPY --from=live / /rootfs
COPY distro/grub.cfg /iso/boot/grub/grub.cfg
RUN echo topOS > /rootfs/etc/hostname \
 && printf '127.0.0.1 localhost\n127.0.1.1 topOS\n' > /rootfs/etc/hosts \
 && mkdir -p /iso/live \
 && cp /rootfs/boot/vmlinuz-* /iso/live/vmlinuz && cp /rootfs/boot/initrd.img-* /iso/live/initrd.img \
 && mksquashfs /rootfs /iso/live/filesystem.squashfs -comp xz -no-progress -e boot \
 && grub-mkrescue -o /topOS.iso /iso -- -volid TOPOS

FROM scratch AS export
COPY --from=iso /topOS.iso /
