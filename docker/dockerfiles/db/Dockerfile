# Keep the existing Alpine/musl PostgreSQL family when adding pgvector.
# Existing volumes must not silently move from musl to glibc.
ARG POSTGRES_IMAGE=postgres:17-alpine
FROM ${POSTGRES_IMAGE} AS extension
RUN apk add --no-cache build-base
ADD --checksum=sha256:cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85 \
    https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.7.tar.gz /tmp/pgvector.tar.gz
RUN tar -xzf /tmp/pgvector.tar.gz -C /tmp \
    && make -C /tmp/pgvector-0.8.7 OPTFLAGS="" with_llvm=no \
    && make -C /tmp/pgvector-0.8.7 install with_llvm=no DESTDIR=/extension

FROM ${POSTGRES_IMAGE}
COPY --from=extension /extension/ /
