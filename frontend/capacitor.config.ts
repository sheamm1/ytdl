import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "app.youfetch.download",
  appName: "YOUFETCH",
  webDir: "dist",
  server: {
    androidScheme: "https",
  },
};

export default config;
