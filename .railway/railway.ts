import {
  defineRailway,
  github,
  postgres,
  preserve,
  project,
  service,
  volume,
} from "railway/iac";

const repository = "ilovemiku520/jjwxc-yuri-analytics";
const productionRegion = "asia-southeast1-eqsg3a";

export default defineRailway(() => {
  const Postgres = postgres("Postgres", { region: productionRegion });
  const backupVolume = volume("backup-volume", {
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
    allowOnlineResize: true,
    region: productionRegion,
    sizeMB: 500,
  });
  const postgresVolume = volume("postgres-volume", {
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
    allowOnlineResize: true,
    region: productionRegion,
    sizeMB: 500,
  });
  const dailyVolume = volume("daily-volume", {
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
    allowOnlineResize: true,
    region: productionRegion,
    sizeMB: 500,
  });
  const api = service("api", {
    source: github(repository, { branch: "main" }),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "apps/api/Dockerfile",
      watchPatterns: [
        "/apps/api/**",
        "/src/**",
        "/migrations/**",
        "/config/**",
        "/contracts/**",
        "/alembic.ini",
        "/pyproject.toml",
      ],
    },
    deploy: {
      healthcheckPath: "/health/ready",
      healthcheckTimeout: 180,
      preDeployCommand: ["pyuri-db migrate --alembic-config /app/alembic.ini"],
      restartPolicyMaxRetries: 3,
      startCommand: "pyuri-api",
    },
    replicas: { [productionRegion]: 1 },
    env: {
      JJYURI_ENABLE_NETWORK: preserve(),
      PORT: preserve(),
      PYURI_API_DEPLOYMENT_SCOPE: preserve(),
      PYURI_API_HOST: preserve(),
      PYURI_API_PORT: preserve(),
      PYURI_COHORT_IMPORT_TOKEN: preserve(),
      PYURI_DATABASE_URL: preserve(),
      PYURI_SHARED_CONSUMER_CONTROLS_ENABLED: preserve(),
    },
  });
  const backup = service("backup", {
    source: github(repository, { branch: "main" }),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "apps/backup/Dockerfile",
      watchPatterns: ["/apps/backup/**"],
    },
    deploy: {
      cronSchedule: "30 20 * * *",
      restartPolicyType: "NEVER",
    },
    replicas: { [productionRegion]: 1 },
    volumeMounts: {
      "/backups": backupVolume,
    },
    env: {
      BACKUP_DIR: preserve(),
      BACKUP_KEEP: preserve(),
      DATABASE_URL: preserve(),
    },
  });
  const daily = service("daily", {
    source: github(repository, { branch: "main" }),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "apps/api/Dockerfile",
      watchPatterns: [
        "/apps/api/**",
        "/src/**",
        "/migrations/**",
        "/config/**",
        "/contracts/**",
        "/alembic.ini",
        "/pyproject.toml",
      ],
    },
    deploy: {
      cronSchedule: "30 19 * * *",
      restartPolicyType: "NEVER",
      startCommand:
        "jjyuri-jjwxc-catalog --index-pages 10 --hydrate-limit 39 --author-limit 10 --request-interval-seconds 2 --cache-dir /data/cache/jjwxc",
    },
    replicas: { [productionRegion]: 1 },
    volumeMounts: {
      "/data/cache": dailyVolume,
    },
    env: {
      JJYURI_ENABLE_NETWORK: preserve(),
      PYURI_DATABASE_URL: preserve(),
    },
  });
  const web = service("web", {
    source: github(repository, { branch: "main" }),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "apps/web/Dockerfile",
      watchPatterns: [
        "/apps/web/**",
        "/package.json",
        "/pnpm-lock.yaml",
        "/pnpm-workspace.yaml",
      ],
    },
    deploy: {
      healthcheckPath: "/",
      healthcheckTimeout: 180,
      restartPolicyMaxRetries: 3,
    },
    replicas: { [productionRegion]: 1 },
    env: {
      PORT: preserve(),
      PYURI_COHORT_IMPORT_TOKEN: preserve(),
      PYURI_INTERNAL_API_URL: preserve(),
    },
  });

  return project("jjwxc-yuri-analytics", {
    resources: [api, Postgres, backup, daily, web, backupVolume, postgresVolume, dailyVolume],
  });
});
