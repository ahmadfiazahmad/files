import type { Config } from "drizzle-kit";

// Reads DATABASE_URL from the environment so this works both locally
// (via .env) and against Railway's injected Postgres connection string
// when running `npm run db:push` with Railway's env vars loaded.
const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error("DATABASE_URL is required to run drizzle-kit push/generate.");
}

export default {
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  dbCredentials: {
    url: databaseUrl,
  },
} satisfies Config;
