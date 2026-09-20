# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
# Spark runs on the JVM. Java 17 is what Spark 4.1 is built and tested against.
COPY --from=eclipse-temurin:17-jre-jammy /opt/java/openjdk /opt/java/openjdk

# The venv lives outside /app so the dev bind mount of ./backend doesn't hide it.
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    JAVA_HOME=/opt/java/openjdk \
    PATH="/opt/venv/bin:/opt/java/openjdk/bin:$PATH"

# Spark's connector for s3a:// paths. It has to be the release of the Hadoop that PySpark bundles
# (3.4.2 for Spark 4.1), together with the AWS SDK that release was built against. Maven Central
# publishes SHA-1 only; both files were checked against it before these SHA-256 sums were taken.
# This sits above the Python layer so that a dependency change does not download 640 MB again.
ADD --chmod=644 --checksum=sha256:d2d24e6b715b5656b9d238bf13b6682a07e2004dd36aad74a73aeb854319f4d9 \
    https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.4.2/hadoop-aws-3.4.2.jar /opt/spark-jars/
ADD --chmod=644 --checksum=sha256:62638f33045690c6bc5e496b54b0b2e89a9ad38cbedacdf6e017fea6bc85f55c \
    https://repo1.maven.org/maven2/software/amazon/awssdk/bundle/2.29.52/bundle-2.29.52.jar /opt/spark-jars/

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Spark loads every jar in PySpark's own jars folder, so the connector is linked into it.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
    && ln -s /opt/spark-jars/*.jar "$(python -c 'import pyspark, os; print(os.path.dirname(pyspark.__file__))')/jars/"
COPY . .
