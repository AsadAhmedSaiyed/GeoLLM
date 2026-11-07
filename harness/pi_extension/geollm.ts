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
      `Allowed input files (inside container: /workspace/input/<filename>): ${allowed.map(f => "/workspace/input/" + f.split(/[/\\]/).pop()).join(", ")}`,


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

  // ---- Plan Proposal Tool ----
  pi.registerTool({
    name: "propose_plan",
    label: "Propose Analysis Plan",
    description:
      "Submit an analysis plan for user review BEFORE writing substantive code. " +
      "Call this after inspecting metadata. Once called, wait for approval.",
    parameters: Type.Object({
      plan: Type.String({
        description: "Markdown describing: hypothesis, bands/indices, methods, and expected outputs.",
      }),
      expected_outputs: Type.Array(Type.String(), {
        description: "Expected filenames like ['water_mask.tif', 'report.png'].",
      }),
    }),
        async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const fs = await import("node:fs");
      const runDir = process.env.GEOLLM_RUN_DIR;
      if (!runDir) {
        return {
          content: [{ type: "text", text: "Error: GEOLLM_RUN_DIR not set." }],
          details: { ok: false, error: "GEOLLM_RUN_DIR not set" },
          isError: true,
        };
      }
      fs.writeFileSync(
        `${runDir}/plan.json`,
        JSON.stringify({ plan: params.plan, outputs: params.expected_outputs }, null, 2),
        "utf-8"
      );
      return {
        content: [
          {
            type: "text",
            text: "Plan submitted to user. Waiting for approval or revision feedback. Do NOT run code until instructed.",
          },
        ],
        details: { ok: true, plan: params.plan, outputs: params.expected_outputs },
        isError: false,
      };
    },
  });

  // ---- Safe Context7 Documentation Lookup Tool ----
  pi.registerTool({
    name: "get_library_docs",
    label: "Get Library Documentation",
    description:
      "Query live Context7 documentation for installed geospatial and scientific libraries. " +
      "Only packages installed in the Docker execution environment are allowed: " +
      "rasterio, geopandas, shapely, pyproj, scipy, numpy, matplotlib, pandas, pillow, affine. " +
      "Uninstalled packages (such as scikit-learn, torch, cv2) will be blocked. " +
      "Use this to check method signatures, parameters, or functions before writing complex code.",
    parameters: Type.Object({
      package: Type.String({
        description: "Library name (e.g. 'rasterio', 'pyproj', 'geopandas', 'scipy', 'shapely').",
      }),
      query: Type.String({
        description: "Specific function, class, or method (e.g. 'Transformer from_crs', 'reproject Resampling', 'kmeans2').",
      }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      return await new Promise((resolve) => {
        const path = require("node:path");
        const docLookupScript = path.resolve(__dirname, "..", "doc_lookup.py");
        const child = spawn(python, [docLookupScript, params.package, params.query], {
          env: process.env,
          stdio: ["pipe", "pipe", "pipe"],
        });

        let output = "";
        child.stdout.on("data", (d: Buffer) => {
          output += d.toString();
        });
        child.stderr.on("data", (d: Buffer) => {
          output += d.toString();
        });
        child.on("close", () => {
          const text = output.trim() || `No documentation found for ${params.package}.${params.query}`;
          resolve({
            content: [{ type: "text", text }],
            details: { package: params.package, query: params.query },
            isError: text.startsWith("BLOCKED"),
          });
        });
        child.on("error", (err: Error) => {
          resolve({
            content: [{ type: "text", text: `Doc lookup error: ${err.message}` }],
            details: { error: err.message },
            isError: true,
          });
        });
      });
    },
  });

  // ---- Autonomous STAC Search Tool ----
  pi.registerTool({
    name: "search_stac",
    label: "Search STAC Satellite Catalog",
    description:
      "Search Microsoft Planetary Computer STAC catalog for satellite scenes matching the user's location, dates, and modality. " +
      "You can pass either a place name (`location_name`) to geocode or an explicit `bbox` ([min_lon, min_lat, max_lon, max_lat]). " +
      "Returns candidate scenes with `id`, `collection`, `datetime`, `cloud_cover`, `aoi_coverage_pct`, `nodata_pct`, signed `thumbnail` URL, available band `assets`, and native resolution memory estimates.",
    parameters: Type.Object({
      location_name: Type.Optional(
        Type.String({ description: "Optional place name to geocode if bbox is not provided (e.g. 'Basra, Iraq', 'Lake Mead')." })
      ),
      bbox: Type.Optional(
        Type.Array(Type.Number(), {
          description: "Geographic bounding box [min_lon, min_lat, max_lon, max_lat] in EPSG:4326.",
        })
      ),
      start_date: Type.String({ description: "Start date in YYYY-MM-DD format." }),
      end_date: Type.String({ description: "End date in YYYY-MM-DD format." }),
      collections: Type.Array(Type.String(), {
        description: "STAC collection IDs, e.g. ['sentinel-2-l2a'], ['landsat-c2-l2'], ['sentinel-1-rtc'], ['cop-dem-glo-30'], ['esa-worldcover'].",
      }),
      max_cloud_cover: Type.Optional(
        Type.Number({ description: "Maximum cloud cover percentage (0-100), e.g. 15." })
      ),
      limit: Type.Optional(
        Type.Number({ description: "Max items to return (default 12)." })
      ),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      return await new Promise((resolve) => {
        const path = require("node:path");
        const stacCli = path.resolve(__dirname, "..", "stac_tool_cli.py");
        const child = spawn(python, [stacCli, "search"], {
          env: process.env,
          stdio: ["pipe", "pipe", "pipe"],
        });

        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
        child.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
        child.on("close", () => {
          try {
            const parsed = JSON.parse(stdout.trim().split("\n").at(-1) ?? "{}");
            resolve({
              content: [{ type: "text", text: JSON.stringify(parsed, null, 2) }],
              details: parsed,
              isError: parsed.ok === false,
            });
          } catch {
            resolve({
              content: [{ type: "text", text: `STAC search failed: ${stderr || stdout}` }],
              details: { ok: false, error: stderr || stdout },
              isError: true,
            });
          }
        });
        child.on("error", (err: Error) => {
          resolve({
            content: [{ type: "text", text: `STAC search error: ${err.message}` }],
            details: { ok: false, error: err.message },
            isError: true,
          });
        });
        child.stdin.write(JSON.stringify(params));
        child.stdin.end();
      });
    },
  });

  // ---- STAC Preview & User Approval Tool ----
  pi.registerTool({
    name: "propose_stac_scenes",
    label: "Show STAC Satellite Preview to User",
    description:
      "Present your selected STAC satellite scenes (with preview thumbnails, dates, cloud cover, AOI coverage %, and bands to download) " +
      "to the user for approval or feedback BEFORE downloading GeoTIFFs or proposing an analysis plan. " +
      "Once called, STOP and wait for user approval or feedback.",
    parameters: Type.Object({
      explanation: Type.String({
        description: "Plain-English explanation for the user describing the selected location, dates, satellite scenes, coverage, and bands.",
      }),
      location_name: Type.Optional(
        Type.String({ description: "Human-readable name of the study area." })
      ),
      bbox: Type.Array(Type.Number(), {
        description: "Target AOI bounding box [min_lon, min_lat, max_lon, max_lat] in EPSG:4326 that will be cropped at 100% original native resolution.",
      }),
      scenes: Type.Array(
        Type.Object({
          collection: Type.String({ description: "STAC collection ID (e.g. 'sentinel-2-l2a')." }),
          item_id: Type.String({ description: "Exact STAC item ID from search_stac results." }),
          datetime: Type.Optional(Type.String({ description: "Scene acquisition datetime." })),
          assets: Type.Array(Type.String(), {
            description: "Band/asset keys to download at native resolution (e.g. ['B02', 'B03', 'B04', 'B08'] or ['vv', 'vh'] or ['data']).",
          }),
          thumbnail: Type.Optional(Type.String({ description: "Signed preview thumbnail URL from search_stac." })),
          cloud_cover: Type.Optional(Type.Number({ description: "Cloud cover percentage." })),
          aoi_coverage_pct: Type.Optional(Type.Number({ description: "AOI overlap percentage." })),
        }),
        { description: "List of selected satellite scenes to preview and stage upon user approval." }
      ),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      return await new Promise((resolve) => {
        const path = require("node:path");
        const stacCli = path.resolve(__dirname, "..", "stac_tool_cli.py");
        const child = spawn(python, [stacCli, "propose_preview"], {
          env: process.env,
          stdio: ["pipe", "pipe", "pipe"],
        });

        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
        child.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });
        child.on("close", () => {
          try {
            const parsed = JSON.parse(stdout.trim().split("\n").at(-1) ?? "{}");
            resolve({
              content: [{ type: "text", text: parsed.message || JSON.stringify(parsed, null, 2) }],
              details: parsed,
              isError: parsed.ok === false,
            });
          } catch {
            resolve({
              content: [{ type: "text", text: `STAC preview submission failed: ${stderr || stdout}` }],
              details: { ok: false, error: stderr || stdout },
              isError: true,
            });
          }
        });
        child.on("error", (err: Error) => {
          resolve({
            content: [{ type: "text", text: `STAC preview error: ${err.message}` }],
            details: { ok: false, error: err.message },
            isError: true,
          });
        });
        child.stdin.write(JSON.stringify(params));
        child.stdin.end();
      });
    },
  });
}
