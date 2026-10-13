// Uses installed Edge, Vite and Node's WebSocket; adds no test dependencies.
import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {readFile, writeFile, mkdtemp, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {createServer} from "vite";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = JSON.parse(await readFile(path.join(frontend, "../data/raw/nmc/official_zones_geometries.geojson"), "utf8"));
const references = source.features.filter(f => ["NN_F_013", "NV_064", "NV_069"].includes(f.properties.zone_id));
const zone = {...references[0].properties, official_capacity: 10, available_capacity: 10, current_vendor_count: 0, live_status: "OPEN"};
const generated = spawnSync(path.join(frontend, "../.venv/Scripts/python.exe"), ["-X", "utf8", "-c", "import json; from backend.pilot_geometry import generate_geographic; print(json.dumps(generate_geographic()))"], {cwd: path.join(frontend, ".."), encoding: "utf8", windowsHide: true});
assert.equal(generated.status, 0, generated.stderr);
const layout = JSON.parse(generated.stdout);
layout.evidence = {analytical_references: references};
layout.revision = "BROWSER_FIXTURE";
layout.slots.forEach(s => {s.updated_at = "2026-10-10T00:00:00Z";});
const server = await createServer({root: frontend, server: {host: "127.0.0.1", port: 5188}, plugins: [{name: "pilot-review-fixture", configureServer(server) {
  server.middlewares.use((req, res, next) => {
    if (req.url?.startsWith("/__pilot_smoke__")) {res.setHeader("Content-Type", "text/html"); res.end('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module" src="/@vite/client"></script><script type="module" src="/tests/pilot-harness.jsx"></script></body></html>');}
    else if (req.url === "/__pilot_fixture__") {res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify({layout, zone}));}
    else next();
  });
}}]});
await server.listen();
const port = server.httpServer.address().port;
const profile = await mkdtemp(path.join(tmpdir(), "nmc-pilot-browser-"));
const reviewOutput = process.argv.includes("--screenshots") ? await mkdtemp(path.join(tmpdir(), "nmc-pilot-review-")) : null;
const edgePath = process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const browser = spawn(edgePath, ["--headless=new", "--disable-gpu", "--no-first-run", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], {windowsHide: true, stdio: "ignore"});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
try {
  let debugPort;
  for (let i = 0; i < 100; i++) {try {debugPort = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); break;} catch {await delay(100);}}
  assert.ok(debugPort, "Edge debugging port is available");
  const pages = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then(r => r.json());
  socket = new WebSocket(pages.find(p => p.type === "page").webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener("open", resolve, {once: true}));
  let seq = 0;
  const pending = new Map();
  const exceptions = [];
  socket.addEventListener("message", event => {const data = JSON.parse(event.data); if (data.id) {const cb = pending.get(data.id); pending.delete(data.id); data.error ? cb.reject(data.error) : cb.resolve(data.result);} else if (data.method === "Runtime.exceptionThrown") exceptions.push(data.params);});
  const command = (method, params = {}) => new Promise((resolve, reject) => {const id = ++seq; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));});
  const evaluate = async expression => {const result = await command("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value;};
  const waitFor = async expression => {for (let i = 0; i < 100; i++) {if (await evaluate(expression)) return; await delay(100);} throw new Error(`Timed out: ${expression}; browser errors: ${JSON.stringify(exceptions.map(e => e.exceptionDetails?.exception?.description || e.exceptionDetails?.text))}`);};
  const click = text => evaluate(`(() => {const b = Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === ${JSON.stringify(text)}); if (!b) throw new Error('Missing button'); for (let p = b.parentElement; p; p = p.parentElement) if (p.tagName === 'DETAILS') p.open = true; b.click();})()`);
  const navigate = async mode => {await command("Page.navigate", {url: `http://127.0.0.1:${port}/__pilot_smoke__?mode=${mode}`});};
  await command("Runtime.enable");
  await command("Page.enable");
  await command("Emulation.setDeviceMetricsOverride", {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
  await navigate("admin");
  await waitFor("document.querySelector('.admin-tabs') && !document.querySelector('.admin-loading-state')");
  await click("Zone Management");
  await evaluate("document.querySelector('.row-detail').click()");
  await click("View Slot Map");
  await waitFor("document.querySelectorAll('.pilot-slot-polygon').length === 10");
  assert.equal(await evaluate("document.querySelector('.admin-drawer') === null"), true);
  await evaluate("window.__desktopY=scrollY;window.__desktopMap=document.querySelector('.pilot-context-map');window.__desktopSize=[window.__desktopMap.clientWidth,window.__desktopMap.clientHeight];true");
  for(const id of ['S010','S009']) {await evaluate(`document.querySelector('.pilot-slot-${id}').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);await waitFor(`document.querySelector('.pilot-details h3').textContent === '${id}'`);assert.equal(await evaluate('scrollY === window.__desktopY'),true);assert.deepEqual(await evaluate('[window.__desktopMap.clientWidth,window.__desktopMap.clientHeight]'),await evaluate('window.__desktopSize'));}
  await evaluate("document.querySelector('.pilot-slot-S005').dispatchEvent(new MouseEvent('click',{bubbles:true}))");
  await waitFor("document.querySelector('.pilot-details h3').textContent === 'S005'");
  await click("Save demonstration slot");
  await waitFor("document.querySelector('.pilot-panel').textContent.includes('S005 demonstration updated.')");
  await click("Layout tools");
  await click("Generate geographic preview");
  await waitFor("!!document.querySelector('.pilot-draft-banner')");
  await evaluate("document.querySelector('.pilot-draft-banner input').click()");
  await click("Save reviewed layout");
  await waitFor("!document.querySelector('.pilot-draft-banner')");
  await click("Edit Slot Layout");
  await waitFor("!!document.querySelector('.pilot-drag-handle')");
  await click("Apply Rotation");
  await waitFor("window.__editValidations > 0");
  await evaluate("document.querySelector('.pilot-draft-banner input').click()");
  await click("Save reviewed layout");
  await waitFor("!document.querySelector('.pilot-draft-banner')");
  await evaluate("window.__pilotMapNode = document.querySelector('.pilot-context-map'); true");
  await click("Back to All Zones");
  await waitFor("!!document.querySelector('.admin-map-canvas')");
  await click("Zone Management");
  await evaluate("document.querySelector('.row-detail').click()");
  await waitFor("!!document.querySelector('.drawer-close')");
  await evaluate("document.querySelector('.drawer-close').click()");
  assert.equal(await evaluate("document.querySelector('.pilot-details h3').textContent"), "S005");
  await evaluate("document.querySelector('.row-detail').click()");
  await click("View Slot Map");
  assert.equal(await evaluate("document.querySelector('.pilot-details h3').textContent"), "S005");
  assert.equal(await evaluate("window.__pilotMapNode === document.querySelector('.pilot-context-map')"), true);
  await click("Layout tools");
  await click("Zoom to selected slot");
  await delay(1500);
  if (reviewOutput) {
    await evaluate("document.querySelectorAll('details').forEach(d => {if (!d.classList.contains('pilot-details')) d.open=false;}); true");
    const shot = await command("Page.captureScreenshot", {format: "png", captureBeyondViewport: true});
    await writeFile(path.join(reviewOutput, "desktop.png"), Buffer.from(shot.data, "base64"));
  }
  await command("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await delay(200);
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, "Mobile page has no horizontal overflow");
  assert.ok(await evaluate("document.querySelector('.pilot-context-map').clientHeight >= 410"), "Large mobile geographic map");
  if (reviewOutput) {
    await evaluate("document.querySelectorAll('details').forEach(d => {if (!d.classList.contains('pilot-details')) d.open=false;}); true");
    const shot = await command("Page.captureScreenshot", {format: "png", captureBeyondViewport: true});
    await writeFile(path.join(reviewOutput, "mobile.png"), Buffer.from(shot.data, "base64"));
    console.log(`Review screenshots: ${reviewOutput}`);
  }
  await navigate("portal-vendor");
  await waitFor("Array.from(document.querySelectorAll('button')).some(b => b.textContent === 'Navigate to My Slot')");
  await click("Navigate to My Slot");
  await waitFor("document.querySelector('.pilot-details h3')?.textContent === 'S002'");
  await click("Back to Dashboard");
  assert.equal(await evaluate("document.querySelector('.pilot-panel').hidden"), true);
  await click("Navigate to My Slot");
  assert.equal(await evaluate("document.querySelector('.pilot-details h3').textContent"), "S002");
  await navigate("vendor");
  await waitFor("document.querySelector('.pilot-details h3')?.textContent === 'S002'");
  assert.equal(await evaluate("document.querySelector('.pilot-details form') === null"), true);
  assert.ok(await evaluate("document.querySelector('.slot-own-access').textContent.includes('My assigned slot: S002')"));
  assert.equal(await evaluate("document.querySelectorAll('.pilot-panel .leaflet-container').length"), 1);
  assert.equal(await evaluate("Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('Start Navigation'))"),false);
  await evaluate("window.__slotMap = document.querySelector('.pilot-context-map');window.__mapSize = [window.__slotMap.clientWidth,window.__slotMap.clientHeight];window.__beforeY=scrollY; true");
  for (const id of ['S010','S009']) {
    await evaluate(`document.querySelector('.pilot-slot-${id}').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
    await waitFor(`document.querySelector('.pilot-details h3').textContent === '${id}'`);
    assert.equal(await evaluate("scrollY === window.__beforeY"),true,'Selection does not scroll');
    assert.equal(await evaluate("window.__slotMap === document.querySelector('.pilot-context-map')"),true,'One persistent map');
    assert.deepEqual(await evaluate("[window.__slotMap.clientWidth,window.__slotMap.clientHeight]"),await evaluate("window.__mapSize"),'Selection does not resize map');
    assert.equal(await evaluate("document.querySelector('.slot-inspector').textContent.includes('PRIVATE_VENDOR')"),false,'Private other-vendor fields never displayed');
  }
  assert.equal(await evaluate("document.querySelectorAll('.pilot-assigned-polygon').length"),1);
  assert.equal(await evaluate("document.querySelector('.pilot-label-assigned').textContent"),'S002');
  assert.equal(await evaluate("document.querySelector('.slot-own-access a') === null"),true,'No directions to centroid without observed access');
  await click("View My Slot"); await waitFor("document.querySelector('.pilot-details h3').textContent === 'S002'");
  await delay(1200);
  if (reviewOutput) {const shot=await command("Page.captureScreenshot",{format:'png',captureBeyondViewport:true});await writeFile(path.join(reviewOutput,'vendor-map-mobile.png'),Buffer.from(shot.data,'base64'));}
  await navigate("vendor-access");await waitFor("!!document.querySelector('.slot-own-access a')");
  assert.ok(await evaluate("document.querySelector('.slot-own-access a').href.includes('destination=19.9744,73.7718')"),'Directions use the recorded access point, not slot centroid');
  await navigate("empty");
  await waitFor("document.querySelector('.slot-inspector')?.textContent.includes('Choose a slot')");
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  for (const width of [1440,390]) {
    await command("Emulation.setDeviceMetricsOverride", {width,height:1000,deviceScaleFactor:1,mobile:width===390});
    for (const mode of ["overview","registry","analysis","review","research-recommendations","portal-requests","portal-profile","portal-vendor","auth","shell-admin","shell-vendor"]) {
      await navigate(mode); await delay(650);
      if (mode === "auth") {await waitFor("!!document.querySelector('.auth-government-header img')"); await evaluate("document.querySelectorAll('.auth-choice button')[1].click()"); await waitFor("!!document.querySelector('input[type=password]')");}
      if (mode.startsWith("shell-")) {await waitFor("!!document.querySelector('.implementation-sidebar .brand img')"); if (width === 390) {await evaluate("document.querySelector('.mobile-menu').click()"); await waitFor("!!document.querySelector('.implementation-sidebar.mobile-open')"); await evaluate("document.querySelector('.mobile-close').click()");}}
      if (mode === "registry") {await waitFor("!!document.querySelector('.hub-table tbody tr')"); assert.equal(await evaluate("document.querySelector('.hub-table tbody').textContent.includes('NN_F_013')"),true,"Registry loads catalog data"); assert.equal(await evaluate("document.querySelector('.hub-error') === null"),true);}
      assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"),true,`${mode} fits ${width}px`);
      if (reviewOutput) {const shot=await command("Page.captureScreenshot",{format:"png",captureBeyondViewport:true});await writeFile(path.join(reviewOutput,`${mode}-${width}.png`),Buffer.from(shot.data,"base64"));}
    }
  }
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log("Browser smoke passed: geographic slots, navigation, registry and desktop/mobile screens. API/provider/GPS responses are fixtures.");
} finally {
  socket?.close();
  browser.kill();
  await server.close();
  await delay(500);
  // The profile is created with mkdtemp under the explicit OS temporary directory.
  assert.ok(profile.startsWith(path.join(tmpdir(), "nmc-pilot-browser-")));
  await rm(profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 300});
}
