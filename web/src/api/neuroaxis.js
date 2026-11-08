import client from "./client";

export const getHealth = () => client.get("/health");
export const getInfra = () => client.get("/infra");
export const postVerify = (runs) => client.post("/verify", { runs });
