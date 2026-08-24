ARG JJYURI_POSTGRES_BASE_IMAGE=postgres:18-alpine
FROM ${JJYURI_POSTGRES_BASE_IMAGE}

COPY apps/backup/run-backup.sh /usr/local/bin/run-jjwxc-backup
RUN chmod 0755 /usr/local/bin/run-jjwxc-backup

ENV BACKUP_DIR=/backups \
    BACKUP_KEEP=7

CMD ["/usr/local/bin/run-jjwxc-backup"]
