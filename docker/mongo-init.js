// Runs once, on the first start of an empty MongoDB volume (mongosh, as root).
// Two users with no overlap: the app user can never read the sealed ground-truth database.
// The role-scoped repositories and the post-verdict unseal rule are built on top of this in BUILD_PLAN Step 1.

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`missing environment variable ${name}`);
  }
  return value;
}

const appDb = required("LEXARENA_MONGO_APP_DB");
const sealedDb = required("LEXARENA_MONGO_SEALED_DB");
if (appDb === sealedDb) {
  throw new Error("LEXARENA_MONGO_APP_DB and LEXARENA_MONGO_SEALED_DB must differ");
}

db.getSiblingDB(appDb).createUser({
  user: required("LEXARENA_MONGO_APP_USER"),
  pwd: required("LEXARENA_MONGO_APP_PASSWORD"),
  roles: [{ role: "readWrite", db: appDb }],
});

db.getSiblingDB(sealedDb).createUser({
  user: required("LEXARENA_MONGO_SEALED_USER"),
  pwd: required("LEXARENA_MONGO_SEALED_PASSWORD"),
  roles: [{ role: "readWrite", db: sealedDb }],
});
