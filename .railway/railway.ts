import { defineRailway, project, service } from "railway/iac";

export default defineRailway(() => {
  const api = service("api", {
    healthcheck: "/api/v1/health",
    healthcheckTimeout: 300,
    preDeploy: "alembic -c alembic.ini upgrade head",
  });

  return project("huce-teaching-assignment-staging", {
    resources: [api],
  });
});
