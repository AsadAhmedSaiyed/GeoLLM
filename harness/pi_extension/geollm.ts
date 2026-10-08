import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const need = (name: string): string => {
  const value = process.env[name];
  if (!value) {
    throw new Error(`geollm extension: environment variable ${name} is not set`);
  }
  return value;
};

export default function (pi: ExtensionAPI) {
  const python = need("GEOLLM_PYTHON");
  const runner = need("GEOLLM_RUNNER");
  const timeoutMs = Number(need("GEOLLM_TOOL_TIMEOUT_S")) * 1000;
  const allowed: string[] = JSON.parse(need("GEOLLM_ALLOWED_FILES"));

  pi.registerTool({
    name: "run_geospatial_code",
    label: "Run Geospatial Code",
    description:
      "Run a complete Python script in an isolated offline Docker sandbox " +
      "(GDAL, rasterio, geopandas, numpy, geollm_lib). " +
      "IMPORTANT: input_files are HOST filesystem paths used only to select " +
      "files for mounting. Inside the Docker sandbox, inputs are available " +
      "under /workspace/input/<filename>. The Python working directory is " +
      "/workspace/output. Never use the host path such as data/file.tif " +
      "inside the sandbox. Prefer dynamically discovering files from " +
      "/workspace/input/. Returns execution status, complete error information, " +
      "sandbox paths, stdout/stderr, results and artifacts. " +
      `Allowed host input files: ${allowed.join(", ")}`,

    parameters: Type.Object({
      code: Type.String({ description: "Complete Python script to execute." }),
      input_files: Type.Array(Type.String(), {
        description: "Input files to mount. Must be from the allowed list.",
      }),
    }),

    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      return await new Promise((resolve) => {
        let stdout = "";
        let stderr = "";
        let finished = false;
        let timer: ReturnType<typeof setTimeout> | undefined;

        // isError=true makes Pi record the call as a failed tool call.
        const finish = (text: string, details: unknown, isError = false) => {
          if (finished) return;
          finished = true;
          if (timer) clearTimeout(timer);
          resolve({
            content: [{ type: "text", text }],
            details,
            isError,
          });
        };

        const child = spawn(python, [runner], {
          env: process.env,
          stdio: ["pipe", "pipe", "pipe"],
        });

        timer = setTimeout(() => {
          child.kill();
          finish(
            `Sandbox runner timed out after ${timeoutMs / 1000}s.`,
            { ok: false, timeout: true },
            true,
          );
        }, timeoutMs);

        signal?.addEventListener(
          "abort",
          () => {
            child.kill();
            finish("Execution aborted.", { ok: false, aborted: true }, true);
          },
          { once: true },
        );

        child.stdout.on("data", (data: Buffer) => {
          stdout += data.toString();
        });
        child.stderr.on("data", (data: Buffer) => {
          stderr += data.toString();
        });

        child.on("error", (error: Error) => {
          finish(`Could not start runner: ${error.message}`, { ok: false }, true);
        });

        child.on("close", (code) => {
          if (finished) return;

          const lines = stdout.trim().split("\n").filter(Boolean);
          const last = lines.at(-1) ?? "";

          try {
            const parsed = JSON.parse(last);
            const message = String(parsed.message ?? parsed.summary ?? last);
            const sandbox = parsed.sandbox;

            const sandboxInfo = sandbox
              ? [
                  "",
                  "SANDBOX PATH CONTRACT:",
                  `Working directory: ${sandbox.working_directory ?? "/workspace/output"}`,
                  `Input directory: ${sandbox.input_directory ?? "/workspace/input"}`,
                  `Output directory: ${sandbox.output_directory ?? "/workspace/output"}`,
                  "Mounted input files:",
                  ...(sandbox.input_files ?? []).map(
                    (f: {
                      filename?: string;
                      sandbox_path?: string;
                      host_path?: string;
                    }) => `- ${f.filename ?? "unknown"}: ${f.sandbox_path ?? "unknown"}`,
                  ),
                ].join("\n")
              : "";

            const errorInfo = parsed.error ? `\n\nERROR:\n${parsed.error}` : "";

            finish(
              `${message}${sandboxInfo}${errorInfo}`,
              parsed,
              parsed.ok === false, // failed sandbox run = tool error
            );
          } catch {
            finish(
              [
                "Runner returned no valid JSON.",
                `exit_code: ${code}`,
                `stdout: ${stdout.slice(-4000)}`,
                `stderr: ${stderr.slice(-4000)}`,
              ].join("\n"),
              {
                ok: false,
                exit_code: code,
                stdout: stdout.slice(-4000),
                stderr: stderr.slice(-4000),
              },
              true,
            );
          }
        });

        child.stdin.write(JSON.stringify(params));
        child.stdin.end();
      });
    },
  });
}