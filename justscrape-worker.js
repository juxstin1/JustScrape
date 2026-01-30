/**
 * JustScrape MCP v1 Node Client
 *
 * Contract enforcement layer. Calls Python worker via stdin/stdout.
 *
 * INVARIANTS (from mcp.json):
 * - No boolean success. Outcomes are classified.
 * - blocked/thin are data, not errors.
 * - classification.status is authoritative.
 * - usable=false is normal operation.
 *
 * Usage:
 *   import { createMCPClient } from "./justscrape-worker.js";
 *   const mcp = await createMCPClient();
 *
 *   // Search only
 *   const search = await mcp.searchSources("web scraping python");
 *
 *   // Retrieve with classification
 *   const result = await mcp.retrieveSource("https://example.com");
 *   if (result.classification.status === "usable") {
 *     console.log(result.content);
 *   }
 *
 *   // Research with failure separation
 *   const research = await mcp.researchWithSources("web scraping tutorial");
 *   console.log(`Usable: ${research.metrics.usable_count}/${research.metrics.total}`);
 */

import { spawn } from "child_process";
import readline from "readline";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Classification status enum (matches mcp.json)
 */
export const Status = {
  USABLE: "usable",
  THIN: "thin",
  BLOCKED: "blocked",
  ENCODING_FAILURE: "encoding-failure",
  EMPTY: "empty",
};

/**
 * Confidence levels (matches mcp.json)
 */
export const Confidence = {
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
};

/**
 * Check if a retrieval result is usable
 * @param {object} result - Result from retrieveSource
 * @returns {boolean}
 */
export function isUsable(result) {
  return result?.classification?.status === Status.USABLE;
}

/**
 * Check if a retrieval was blocked (bot wall, captcha)
 * @param {object} result - Result from retrieveSource
 * @returns {boolean}
 */
export function isBlocked(result) {
  return result?.classification?.status === Status.BLOCKED;
}

/**
 * Check if content is thin (<500 chars)
 * @param {object} result - Result from retrieveSource
 * @returns {boolean}
 */
export function isThin(result) {
  return result?.classification?.status === Status.THIN;
}

/**
 * Create MCP client connected to Python worker
 * @param {object} options
 * @param {string} options.pythonPath - Path to Python executable
 * @param {string} options.workerPath - Path to worker.py
 * @returns {Promise<object>} MCP client
 */
export async function createMCPClient(options = {}) {
  // Default to system Python (no venv assumption)
  const pythonPath = options.pythonPath || "python";
  const workerPath = options.workerPath || path.join(__dirname, "worker.py");

  const proc = spawn(pythonPath, [workerPath], {
    cwd: __dirname,
    stdio: ["pipe", "pipe", "inherit"],
  });

  const rl = readline.createInterface({ input: proc.stdout });

  let ready = false;
  let version = null;
  const queue = [];

  // Handle process errors
  proc.on("error", (err) => {
    console.error("[MCP] Worker process error:", err.message);
  });

  proc.on("exit", (code) => {
    // Reject any pending requests
    while (queue.length > 0) {
      const { reject } = queue.shift();
      reject(new Error(`Worker exited with code ${code}`));
    }
  });

  // Parse worker responses
  rl.on("line", (line) => {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch (e) {
      console.error("[MCP] Failed to parse response:", line);
      return;
    }

    // First message is ready signal
    if (!ready) {
      if (msg.ok && msg.status === "ready") {
        ready = true;
        version = msg.version;
      }
      return;
    }

    // Subsequent messages are responses
    if (queue.length === 0) {
      console.warn("[MCP] Response with no pending request");
      return;
    }

    const { resolve, reject } = queue.shift();
    if (msg.ok) {
      resolve(msg.result);
    } else {
      reject(new Error(msg.error));
    }
  });

  // Wait for ready signal
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("Worker startup timeout"));
    }, 10000);

    const checkReady = setInterval(() => {
      if (ready) {
        clearTimeout(timeout);
        clearInterval(checkReady);
        resolve();
      }
    }, 50);
  });

  /**
   * Call a worker tool
   * @param {string} tool - Tool name
   * @param {object} args - Tool arguments
   * @returns {Promise<object>}
   */
  function call(tool, args) {
    return new Promise((resolve, reject) => {
      if (!proc.stdin.writable) {
        reject(new Error("Worker stdin not writable"));
        return;
      }
      queue.push({ resolve, reject });
      proc.stdin.write(JSON.stringify({ tool, args }) + "\n");
    });
  }

  // Return MCP v1 client interface
  return {
    /**
     * MCP version
     */
    version,

    /**
     * Search via DuckDuckGo. Returns ranked results without content.
     * @param {string} query - Search query
     * @param {number} numResults - Max results (default 10, max 25)
     * @returns {Promise<object>}
     */
    searchSources: (query, numResults = 10) =>
      call("search_sources", { query, num_results: numResults }),

    /**
     * Retrieve and classify a single URL.
     *
     * NEVER returns boolean success.
     * Check result.classification.status for outcome.
     *
     * @param {string} url - URL to retrieve
     * @param {boolean} allowJavascript - Allow Playwright (default true)
     * @returns {Promise<object>} { url, title, content, signals, classification }
     */
    retrieveSource: (url, allowJavascript = true) =>
      call("retrieve_source", { url, allow_javascript: allowJavascript }),

    /**
     * Search + retrieve with explicit failure separation.
     *
     * Returns:
     * - sources: Only usable sources with content
     * - failures: Blocked/thin/error with reasons
     * - metrics: usable_rate, blocked_count, etc.
     *
     * @param {string} query - Search query
     * @param {number} limit - Number of results (default 5, max 10)
     * @param {boolean} allowJavascript - Allow Playwright (default true)
     * @param {number} maxContentLength - Truncate content (default 5000)
     * @returns {Promise<object>}
     */
    researchWithSources: (query, limit = 5, allowJavascript = true, maxContentLength = 5000) =>
      call("research_with_sources", {
        query,
        limit,
        allow_javascript: allowJavascript,
        max_content_length: maxContentLength,
      }),

    /**
     * Extract links from a page.
     * @param {string} url - URL to extract from
     * @param {boolean} filterExternal - Only external links (default false)
     * @returns {Promise<object>} { source_url, urls, count }
     */
    extractUrls: (url, filterExternal = false) =>
      call("extract_urls", { url, filter_external: filterExternal }),

    /**
     * Raw tool call (for advanced use)
     */
    call,

    /**
     * Shutdown worker
     */
    kill: () => proc.kill(),

    /**
     * Check if worker is ready
     */
    isReady: () => ready,
  };
}

// Legacy export for backwards compatibility (deprecated)
export function startJustScrapeWorker(options = {}) {
  console.warn("[MCP] startJustScrapeWorker is deprecated. Use createMCPClient instead.");

  // Return a sync wrapper that creates client on first call
  let clientPromise = null;

  const getClient = () => {
    if (!clientPromise) {
      clientPromise = createMCPClient(options);
    }
    return clientPromise;
  };

  return {
    webSearch: async (query, numResults = 10) => {
      const client = await getClient();
      return client.searchSources(query, numResults);
    },
    scrapeUrl: async (url) => {
      const client = await getClient();
      return client.retrieveSource(url);
    },
    searchAndScrape: async (query, limit = 3, maxContentLength = 5000) => {
      const client = await getClient();
      return client.researchWithSources(query, limit, true, maxContentLength);
    },
    extractUrls: async (url, filterExternal = false) => {
      const client = await getClient();
      return client.extractUrls(url, filterExternal);
    },
    kill: async () => {
      if (clientPromise) {
        const client = await clientPromise;
        client.kill();
      }
    },
    isReady: () => clientPromise !== null,
  };
}

// =============================================================================
// CLI Test Mode - Validates MCP contract
// =============================================================================

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  console.log("MCP v1 Contract Validation\n");

  const mcp = await createMCPClient();
  console.log(`Worker version: ${mcp.version}\n`);

  // Test 1: Search
  console.log("--- searchSources ---");
  const search = await mcp.searchSources("web scraping python", 3);
  console.log(`Results: ${search.results?.length || 0}`);
  console.log(`Cached: ${search.cached}`);

  // Test 2: Retrieve with classification (usable case)
  console.log("\n--- retrieveSource (Wikipedia - expect usable) ---");
  const wiki = await mcp.retrieveSource("https://en.wikipedia.org/wiki/Web_scraping");
  console.log(`Status: ${wiki.classification.status}`);
  console.log(`Confidence: ${wiki.classification.confidence}`);
  console.log(`Content length: ${wiki.signals.content_length}`);
  console.log(`Method: ${wiki.signals.method}`);
  console.log(`Is usable: ${isUsable(wiki)}`);

  // Test 3: Retrieve with classification (blocked case)
  console.log("\n--- retrieveSource (Medium - expect blocked) ---");
  const medium = await mcp.retrieveSource("https://medium.com/@example/test");
  console.log(`Status: ${medium.classification.status}`);
  console.log(`Confidence: ${medium.classification.confidence}`);
  console.log(`Content length: ${medium.signals.content_length}`);
  console.log(`Detected patterns: ${medium.classification.detected_patterns.join(", ") || "none"}`);
  console.log(`Is blocked: ${isBlocked(medium)}`);

  // Test 4: Research with failure separation
  console.log("\n--- researchWithSources ---");
  const research = await mcp.researchWithSources("python web scraping tutorial", 5);
  console.log(`Total: ${research.metrics.total}`);
  console.log(`Usable: ${research.metrics.usable_count}`);
  console.log(`Usable rate: ${(research.metrics.usable_rate * 100).toFixed(0)}%`);
  console.log(`Blocked: ${research.metrics.blocked_count}`);
  console.log(`Thin: ${research.metrics.thin_count}`);

  console.log("\nUsable sources:");
  for (const s of research.sources) {
    console.log(`  [${s.status}] ${s.content_length} chars - ${s.title?.slice(0, 50)}`);
  }

  console.log("\nFailures:");
  for (const f of research.failures) {
    console.log(`  [${f.status}] ${f.title?.slice(0, 50)} - ${f.reason?.join(", ")}`);
  }

  mcp.kill();
  console.log("\n[OK] Contract validation complete");
}
