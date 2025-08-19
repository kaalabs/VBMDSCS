  // UUID's
  const UART_SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
  const UART_RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'; // write
  const UART_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'; // notify
  const BLE_NAME = 'VBMCSWT'; // filter op exact naam of prefix

  // UI refs
  const ui = {
    btnConnect: document.getElementById('btnConnect'),
    btnDisconnect: document.getElementById('btnDisconnect'),
    autoReconnect: document.getElementById('autoReconnect'),
    modeExpert: document.getElementById('modeExpert'),
    connBadge: document.getElementById('connBadge'),
    stateBadge: document.getElementById('stateBadge'),
    readyBadge: document.getElementById('readyBadge'),
    pct: document.getElementById('pct'),
    lvlFill: document.getElementById('lvlFill'),
    cmds: Array.from(document.querySelectorAll('.cmd')),
    btnAutoCal: document.getElementById('btnAutoCal'),
    stepsPanel: document.getElementById('stepsPanel'),
    stepBadge: document.getElementById('stepBadge'),
    stepMsg: document.getElementById('stepMsg'),
    stepBack: document.getElementById('stepBack'),
    stepCancel: document.getElementById('stepCancel'),
    stepNext: document.getElementById('stepNext'),
    infoDump: document.getElementById('infoDump'),
    cfgDump: document.getElementById('cfgDump'),
    log: document.getElementById('log'),
    ema: document.getElementById('ema'),
    obs: document.getElementById('obs'),
    userHintRow: document.getElementById('userHintRow'),
    userHintBox: document.getElementById('userHintBox'),
    userHintDot: document.getElementById('userHintDot'),
    userHint: document.getElementById('userHint'),
    btnCfgReset: document.getElementById('btnCfgReset'),
    btnExportLog: document.getElementById('btnExportLog'),
    testIndicatorRow: document.getElementById('testIndicatorRow'),
  };

  let device=null, server=null, rxChar=null, txChar=null, buffer='';
  
  // Robuuste BLE communicatie
  let writeQueue = [];
  let isWriting = false;
  let reconnectTimer = null;
  let testPollTimer = null;
  let statusPollTimer = null;
  let isExpert = false;
  let lastState = null, lastPct = null, lastReady = null;
  let testActive = false;
  let lastTestActive = null;
  let currentTestId = null;
  
  // Robustness controls
  let preferTestStream = false;
  let lastTestMsgTs = 0;
  const TEST_INACTIVE_DEBOUNCE_MS = 1500;
  let lastSeqStatus = -1;
  let lastSeqTest = -1;
  
  // BLE timeout en retry instellingen
  const BLE_WRITE_TIMEOUT_MS = 5000;
  const BLE_RETRY_DELAY_MS = 1000;
  const MAX_RETRIES = 3;

  function now() { return new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
  
  function log(line, kind) {
    const div = document.createElement('div');
    if (kind === 'error') div.style.color = '#991b1b';
    else if (kind === 'warn') div.style.color = '#92400e';
    else if (kind === 'send') div.style.color = '#1e40af';
    div.textContent = '[' + now() + '] ' + line;
    ui.log.prepend(div);
    while (ui.log.children.length > 300) ui.log.removeChild(ui.log.lastChild);
  }

  function setConn(state) {
    ui.connBadge.textContent = state;
    ui.connBadge.className = 'badge ' + (state === 'connected' ? 'b-green' : 'b-gray');
    
    // Update connection buttons
    ui.btnConnect.disabled = (state === 'connected');
    ui.btnDisconnect.disabled = (state !== 'connected');
    
    // Reset UI indicators when not connected
    if (state !== 'connected') {
      if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null; }
      lastState = null; 
      lastPct = null; 
      lastReady = null;
      setStateBadge('—');
      setReadyBadge(null);
      updateGauge(null);
      try { 
        if (ui.infoDump) ui.infoDump.textContent = '—'; 
        if (ui.cfgDump) ui.cfgDump.textContent = '—'; 
      } catch(e) {}
    } else {
      // Start heartbeat polling (INFO?) elke 2s voor snellere UI updates
      if (!statusPollTimer) {
        statusPollTimer = setInterval(() => {
          if (!testActive && rxChar) { // pauzeer tijdens test
            sendCmd('INFO?').catch(() => {});
          }
        }, 2000);
      }
    }
  }

  // Robuuste BLE write functie met timeout en retry
  async function robustWrite(data, retries = 0) {
    if (!rxChar) {
      throw new Error('Niet verbonden');
    }
    
    try {
      // Timeout wrapper
      const writePromise = rxChar.writeValue(new TextEncoder().encode(data + '\n'));
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Write timeout')), BLE_WRITE_TIMEOUT_MS)
      );
      
      await Promise.race([writePromise, timeoutPromise]);
      log(`[BLE] Verzonden: ${data}`, 'send');
      return true;
      
    } catch (error) {
      log(`[BLE] Write fout (poging ${retries + 1}): ${error.message}`, 'error');
      
      if (retries < MAX_RETRIES) {
        log(`[BLE] Retry over ${BLE_RETRY_DELAY_MS}ms...`, 'warn');
        await new Promise(resolve => setTimeout(resolve, BLE_RETRY_DELAY_MS));
        return robustWrite(data, retries + 1);
      } else {
        throw new Error(`Write mislukt na ${MAX_RETRIES} pogingen: ${error.message}`);
      }
    }
  }

  // Queue-based write systeem
  async function processWriteQueue() {
    if (isWriting || writeQueue.length === 0) return;
    
    isWriting = true;
    
    while (writeQueue.length > 0) {
      const { data, resolve, reject } = writeQueue.shift();
      
      try {
        await robustWrite(data);
        resolve(true);
      } catch (error) {
        reject(error);
      }
      
      // Kleine pauze tussen writes om GATT operaties te voorkomen
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    
    isWriting = false;
  }

  // Verbeterde sendCmd functie
  async function sendCmd(cmd) {
    if (!rxChar) {
      log('Niet verbonden', 'error');
      return false;
    }
    
    return new Promise((resolve, reject) => {
      writeQueue.push({ data: cmd, resolve, reject });
      processWriteQueue();
    });
  }

  // Verbeterde connectie setup
  async function setupGatt() {
    try {
      const service = await server.getPrimaryService(UART_SERVICE);
      rxChar = await service.getCharacteristic(UART_RX);
      txChar = await service.getCharacteristic(UART_TX);
      
      // Enable notifications met error handling
      await txChar.startNotifications();
      txChar.addEventListener('characteristicvaluechanged', onNotify);
      
      log('GATT setup voltooid');
      return true;
    } catch (error) {
      log(`GATT setup mislukt: ${error.message}`, 'error');
      throw error;
    }
  }

  // Verbeterde device selection
  async function chooseAndConnect() {
    try {
      const dev = await navigator.bluetooth.requestDevice({
        filters: [
          { name: BLE_NAME },
          { namePrefix: BLE_NAME },
        ],
        optionalServices: [UART_SERVICE]
      });
      
      device = dev;
      device.addEventListener('gattserverdisconnected', onDisc);
      
      server = await device.gatt.connect();
      await setupGatt();
      
      setConn('connected');
      enableCmds(true);
      
      log('Verbonden met ' + (device.name || 'apparaat'));
      
      // Initial data request met retry
      await sendCmdWithRetry('INFO?');
      await sendCmdWithRetry('CFG?');
      
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
      
      return true;
    } catch (error) {
      log(`Device selection mislukt: ${error.message}`, 'error');
      throw error;
    }
  }

  // Helper functie voor commando's met retry
  async function sendCmdWithRetry(cmd, maxRetries = 2) {
    for (let i = 0; i <= maxRetries; i++) {
      try {
        await sendCmd(cmd);
        return true;
      } catch (error) {
        if (i === maxRetries) {
          log(`Commando ${cmd} mislukt na ${maxRetries + 1} pogingen`, 'error');
          throw error;
        }
        log(`Retry ${cmd} (${i + 1}/${maxRetries})`, 'warn');
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    }
  }

  async function connect() {
    try {
      // Als we al een device hebben, probeer direct te verbinden
      if (device) {
        device.removeEventListener && device.removeEventListener('gattserverdisconnected', onDisc);
        device.addEventListener('gattserverdisconnected', onDisc);
        
        if (!device.gatt.connected) {
          try {
            server = await device.gatt.connect();
            await setupGatt();
            setConn('connected');
            enableCmds(true);
            log('Opnieuw verbonden met ' + (device.name || 'apparaat'));
          } catch (e) {
            log('Herverbinden mislukt, open device chooser...', 'warn');
            device = null;
            server = null;
            rxChar = null;
            txChar = null;
            await chooseAndConnect();
            return;
          }
        } else {
          setConn('connected');
          enableCmds(true);
        }
        
        await sendCmdWithRetry('INFO?');
        await sendCmdWithRetry('CFG?');
        
        if (reconnectTimer) {
          clearInterval(reconnectTimer);
          reconnectTimer = null;
        }
        return;
      }
      
      await chooseAndConnect();
    } catch (e) {
      log('Connectie mislukt: ' + (e.message || e), 'error');
      setConn('error');
    }
  }

  async function reconnect() {
    if (!device) return;
    
    try {
      if (!device.gatt.connected) {
        await new Promise(resolve => setTimeout(resolve, 150));
        server = await device.gatt.connect();
        await setupGatt();
        setConn('connected');
        enableCmds(true);
        log('Opnieuw verbonden met ' + (device.name || 'apparaat'));
        
        await sendCmdWithRetry('INFO?');
        await sendCmdWithRetry('CFG?');
        
        if (reconnectTimer) {
          clearInterval(reconnectTimer);
          reconnectTimer = null;
        }
      }
    } catch (e) {
      log('Reconnect mislukt: ' + (e.message || e), 'warn');
      
      if (ui.autoReconnect.checked && !reconnectTimer) {
        reconnectTimer = setInterval(reconnect, 2000);
      }
    }
  }

  async function disconnect() {
    try {
      if (device && device.gatt.connected) {
        device.gatt.disconnect();
      }
    } catch (e) {
      log('Disconnect error: ' + e.message, 'warn');
    }
  }

  function onDisc() {
    rxChar = null;
    txChar = null;
    server = null;
    
    // Clear write queue
    writeQueue.forEach(({ reject }) => reject(new Error('Disconnected')));
    writeQueue = [];
    isWriting = false;
    
    // Reset test status
    testActive = false;
    lastTestActive = false;
    preferTestStream = false;
    currentTestId = null;
    if (statusPollTimer) { clearInterval(statusPollTimer); statusPollTimer = null; }
    
    enableCmds(false);
    setConn('idle');
    setTestIndicator(false);
    log('Bluetooth disconnected', 'warn');
    
    if (ui.autoReconnect.checked && device) {
      if (!reconnectTimer) {
        reconnectTimer = setInterval(reconnect, 2000);
      }
      setTimeout(reconnect, 1000);
    }
  }

  function onNotify(ev) {
    try {
      const data = new TextDecoder().decode(ev.target.value);
      buffer += data;
      
      log(`[BLE] Raw data ontvangen: "${data}"`, 'warn');
      
      // Process complete JSON messages
      const jsonMessages = extractJson(buffer);
      log(`[BLE] ${jsonMessages.length} JSON berichten gevonden in buffer`, 'warn');
      
      for (const js of jsonMessages) {
        try {
          log(`[BLE] Probeer JSON te parsen: "${js}"`, 'warn');
          const o = JSON.parse(js);
          log(`[BLE] JSON succesvol geparsed: ${JSON.stringify(o)}`, 'warn');
          
          // Process message...
          processMessage(o);
          
        } catch (parseError) {
          log(`JSON parse fout: ${parseError.message}`, 'error');
          log(`Problematische JSON: "${js}"`, 'error');
        }
      }
      
      // Buffer cleanup
      const lc = buffer.lastIndexOf('}');
      const lo = buffer.lastIndexOf('{');
      if (lc > -1 && lc > lo) {
        buffer = buffer.slice(lc + 1);
      } else if (buffer.length > 2048) {
        buffer = buffer.slice(-1024);
      }
      
    } catch (error) {
      log(`Notify error: ${error.message}`, 'error');
    }
  }

  // Helper functie om JSON berichten te extraheren
  function extractJson(buffer) {
    const results = [];
    let braceCount = 0;
    let start = -1;
    
    for (let i = 0; i < buffer.length; i++) {
      if (buffer[i] === '{') {
        if (braceCount === 0) start = i;
        braceCount++;
      } else if (buffer[i] === '}') {
        braceCount--;
        if (braceCount === 0 && start !== -1) {
          results.push(buffer.slice(start, i + 1));
          start = -1;
        }
      }
    }
    
    return results;
  }

  // Helper functie om berichten te verwerken
  function processMessage(o) {
    log(`[PROCESS] Verwerk bericht: ${JSON.stringify(o)}`, 'warn');
    
    const isTestEvent = (o.evt === 'test');
    
    // Sequence tracking
    if ('seq' in o) {
      const s = Number(o.seq);
      if (isTestEvent) {
        if (lastSeqTest >= 0 && s < lastSeqTest) {
          log('Ignoring out-of-order TEST seq ' + s + ' < ' + lastSeqTest, 'warn');
          return;
        }
        lastSeqTest = s;
      } else {
        if (lastSeqStatus >= 0 && s < lastSeqStatus) {
          log('Ignoring out-of-order STATUS seq ' + s + ' < ' + lastSeqStatus, 'warn');
          return;
        }
        lastSeqStatus = s;
      }
    }
    
    // State updates - toon altijd ook tijdens test
    if ('state' in o) {
      log(`[DASHBOARD] State update: ${o.state} (was: ${lastState})`, 'warn');
      setStateBadge(o.state);
      lastState = o.state;
    }
    
    if ('pct' in o) {
      log(`[DASHBOARD] Pct update: ${o.pct}% (was: ${lastPct}%)`, 'warn');
      // Als firmware None stuurt bij sensorfout, toon '—' en 0%
      if (o.pct === null || typeof o.pct === 'undefined') {
        updateGauge(null);
        lastPct = null;
      } else {
        updateGauge(o.pct);
        lastPct = o.pct;
      }
    }
    
    // Extra UI velden
    if ('ema_mm' in o) {
      try { ui.ema.textContent = (o.ema_mm == null ? '—' : Number(o.ema_mm).toFixed(1)); } catch(e) {}
    }
    if ('obs_min' in o || 'obs_max' in o) {
      const mn = ('obs_min' in o) ? o.obs_min : '—';
      const mx = ('obs_max' in o) ? o.obs_max : '—';
      try { ui.obs.textContent = `${mn}..${mx}`; } catch(e) {}
    }
    
    // Ready status
    if ('ready' in o) {
      log(`[DASHBOARD] Ready update: ${o.ready}`, 'warn');
      setReadyBadge(o.ready);
      lastReady = o.ready;
    }
    
    // Test events
    if (o.evt === 'test') {
      log(`[TEST] Test event ontvangen`, 'warn');
      preferTestStream = true;
      lastTestMsgTs = Date.now();
      
      if ('test_data_id' in o) {
        if (currentTestId === null || o.test_data_id >= currentTestId) {
          currentTestId = o.test_data_id;
        }
      }
    }
    
    // Test status - verbeterde handling
    if ('test_active' in o) {
      const active = !!o.test_active;
      log(`[TEST] Test active update: ${active}`, 'warn');
      if (lastTestActive !== active) {
        log('TEST active: ' + (active ? 'yes' : 'no'));
        lastTestActive = active;
        testActive = active; // Update globale testActive variabele
        
        if (active) {
          preferTestStream = true;
          lastTestMsgTs = Date.now();
          setTestIndicator(true);
          // Heartbeat pauzeren tijdens test
          // (timer blijft bestaan maar INFO? wordt niet verstuurd zolang testActive=true)
        } else {
          // Test gestopt - reset
          preferTestStream = false;
          currentTestId = null;
          setTestIndicator(false);
          // Na stoppen direct een INFO? forceren voor snelle UI sync
          try { sendCmd('INFO?'); } catch(e) {}
          log('Test gestopt - alle test indicatoren gereset');
        }
      }
      
      if ('test_data_id' in o) {
        currentTestId = o.test_data_id;
        log('Test session ID: ' + currentTestId);
      }
    }
    
    // Test stop event handling
    if (o.evt === 'test_stopped') {
      log('TEST STOPPED event ontvangen', 'warn');
      testActive = false;
      lastTestActive = false;
      preferTestStream = false;
      currentTestId = null;
      setTestIndicator(false);
      log('Test gestopt via event - alle indicatoren gereset');
    }
    
    // Config / Info dumps
    const isCfg = !isTestEvent && (
      ('uart_port' in o) || ('uart_rx' in o) || ('uart_tx' in o) ||
      ('min_mm' in o) || ('max_mm' in o) || ('timeout_ms' in o) || ('sample_hz' in o) ||
      ('hysteresis_pct' in o) || ('low_pct' in o) || ('bottom_pct' in o) ||
      ('allow_pump_at_low' in o) || ('interlock_active' in o) || ('use_pump_ok' in o) || ('use_heater_ok' in o) ||
      ('ble_enabled' in o) || ('ble_name' in o)
    );
    const isInfo = !isTestEvent && (('cal_empty_mm' in o) || ('cal_full_mm' in o));
    if (isInfo) {
      try { if (ui.infoDump) ui.infoDump.textContent = JSON.stringify(o, null, 2); } catch (e) { if (ui.infoDump) ui.infoDump.textContent = String(o); }
    } else if (isCfg) {
      try { if (ui.cfgDump) ui.cfgDump.textContent = JSON.stringify(o, null, 2); } catch (e) { if (ui.cfgDump) ui.cfgDump.textContent = String(o); }
    }
    
    // Update user hint
    log(`[HINT] Update user hint met: state=${lastState}, pct=${lastPct}, ready=${lastReady}`, 'warn');
    setUserHint(lastState, lastPct, lastReady);
    
    log(`[PROCESS] Bericht verwerking voltooid`, 'warn');
  }

  function enableCmds(on) { 
    ui.cmds.forEach(b => b.disabled = !on); 
    ui.btnAutoCal.disabled = !on; 
  }

  function setStateBadge(st) {
    log(`[UI] setStateBadge aangeroepen met: ${st}`, 'warn');
    const map = { OK: 'b-green', LOW: 'b-yellow', BOTTOM: 'b-red', FAULT: 'b-red' };
    ui.stateBadge.textContent = st || '—';
    ui.stateBadge.className = 'badge ' + (map[st] || 'b-gray');
    // Kleur van de vullingsbalk koppelen aan status
    let tone = '';
    if (st === 'OK') tone = 'tone-green';
    else if (st === 'LOW') tone = 'tone-yellow';
    else if (st === 'BOTTOM' || st === 'FAULT') tone = 'tone-red';
    ui.lvlFill.className = tone;
    // Inline kleur zetten om CSS-specificiteit van .bar > div te overrulen
    let bg = 'var(--blue)';
    if (st === 'OK') bg = 'var(--good)';
    else if (st === 'LOW') bg = 'var(--warn)';
    else if (st === 'BOTTOM' || st === 'FAULT') bg = 'var(--bad)';
    ui.lvlFill.style.background = bg;
    log(`[UI] State badge bijgewerkt naar: ${st}`, 'warn');
  }

  function setReadyBadge(ready) {
    log(`[UI] setReadyBadge aangeroepen met: ${ready}`, 'warn');
    ui.readyBadge.textContent = ready === null ? '—' : (ready ? 'READY' : 'NOT READY');
    ui.readyBadge.className = 'badge ' + (ready === null ? 'b-gray' : (ready ? 'b-green' : 'b-red'));
    log(`[UI] Ready badge bijgewerkt naar: ${ready}`, 'warn');
  }

  function updateGauge(pct) {
    log(`[UI] updateGauge aangeroepen met: ${pct}`, 'warn');
    if (pct === null) {
      ui.pct.textContent = '—';
      ui.lvlFill.style.width = '0%';
      log(`[UI] Gauge gereset naar leeg`, 'warn');
      return;
    }
    
    // Zorg ervoor dat de balk altijd wordt getoond
    ui.pct.textContent = pct.toFixed(1) + '%';
    ui.lvlFill.style.width = pct + '%';
    
    // Debug logging
    log(`[GAUGE] Waterniveau bijgewerkt: ${pct.toFixed(1)}%`, 'warn');
    log(`[UI] Gauge bijgewerkt: percentage=${pct.toFixed(1)}%, balk-breedte=${pct}%`, 'warn');
  }

  function setUserHint(state, pct, ready) {
    log(`[UI] setUserHint aangeroepen met: state=${state}, pct=${pct}, ready=${ready}`, 'warn');
    
    // Toon altijd de hint als er percentage data is, ook tijdens tests
    if (pct === null && !state) {
      log(`[UI] Geen data beschikbaar, verberg user hint`, 'warn');
      ui.userHintRow.classList.add('hidden');
      return;
    }
    
    let txt = '—';
    let boxClass = 'user-hint';
    let dotClass = 'uh-dot';
    
    if (ready === false) { 
      txt = 'Initialiseren…'; 
      // neutral styling - no additional classes
    } else if (state === 'OK') { 
      txt = 'Niveau OK'; 
      boxClass += ' uh-ok'; 
      dotClass += ' ok'; 
    } else if (state === 'LOW') { 
      txt = 'Niveau laag — vul de tank bij'; 
      boxClass += ' uh-low'; 
      dotClass += ' low'; 
    } else if (state === 'BOTTOM') { 
      txt = 'Tank leeg — machine beveiligd. Vul de tank.'; 
      boxClass += ' uh-bottom'; 
      dotClass += ' bottom'; 
    } else if (state === 'FAULT') { 
      txt = 'Sensorstoring — controleer sensor/verbinding'; 
      boxClass += ' uh-fault'; 
      dotClass += ' fault'; 
    } else if (pct !== null) {
      // Als er geen state is maar wel percentage, toon generieke tekst
      txt = `Niveau: ${pct.toFixed(1)}%`;
    }
    
    log(`[UI] User hint tekst: "${txt}"`, 'warn');
    log(`[UI] User hint classes: box=${boxClass}, dot=${dotClass}`, 'warn');
    
    ui.userHint.textContent = txt;
    ui.userHintBox.className = boxClass;
    ui.userHintDot.className = dotClass;
    ui.userHintRow.classList.remove('hidden');
    
    log(`[UI] User hint bijgewerkt en zichtbaar gemaakt`, 'warn');
  }

  function setTestIndicator(active) {
    if (active) {
      ui.testIndicatorRow.classList.remove('hidden');
      // Behoud de originele styling
    } else {
      ui.testIndicatorRow.classList.add('hidden');
    }
  }

  function applyMode() {
    isExpert = ui.modeExpert.checked;
    try { localStorage.setItem('wt_mode', isExpert ? 'expert' : 'normal'); } catch(e){}
    
    // Toggle expert-only UI elements
    const expertElements = document.querySelectorAll('.expert');
    expertElements.forEach(el => {
      if (el.id === 'stepsPanel') return; // beheerd via open/closeSteps
      if (isExpert) {
        el.classList.remove('hidden');
      } else {
        el.classList.add('hidden');
      }
    });
    
    // Toggle user-only UI elements
    const userElements = document.querySelectorAll('.user');
    userElements.forEach(el => {
      if (isExpert) {
        el.classList.add('hidden');
      } else {
        el.classList.remove('hidden');
      }
    });
    
    // Bij modewissel de hint updaten met laatste bekende waarden
    setUserHint(lastState, lastPct, lastReady);
    setTestIndicator(testActive);
  }

  function exportLog() {
    const lines = Array.from(ui.log.children).reverse().map(n => n.textContent);
    const blob = new Blob([lines.join('\n')], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; 
    a.download = 'watertank_log.txt'; 
    a.click();
    URL.revokeObjectURL(url);
  }

  // Inline Auto-Cal flow
  let step = 0; // 0=closed, 1=FULL, 2=EMPTY
  
  function delay(ms) { 
    return new Promise(r => setTimeout(r, ms)); 
  }
  
  function openSteps() { 
    if (!rxChar) { 
      log('Niet verbonden', 'warn'); 
      return; 
    } 
    step = 1; 
    ui.stepsPanel.classList.remove('hidden'); 
    ui.stepBack.disabled = true; 
    ui.stepNext.textContent = 'Markeer FULL'; 
    ui.stepBadge.textContent = 'Stap 1/2'; 
    ui.stepMsg.textContent = 'Vul de tank volledig en wacht tot het niveau stabiel is. Klik op "Markeer FULL".'; 
    enableCmds(false); 
    ui.btnAutoCal.disabled = true; 
  }
  
  function closeSteps() { 
    step = 0; 
    ui.stepsPanel.classList.add('hidden'); 
    enableCmds(true); 
  }
  
  async function nextStep() { 
    if (step === 1) { 
      await sendCmd('INFO?'); 
      await delay(200); 
      await sendCmd('CAL FULL'); 
      log('CAL FULL verstuurd'); 
      step = 2; 
      ui.stepBack.disabled = false; 
      ui.stepNext.textContent = 'Markeer EMPTY'; 
      ui.stepBadge.textContent = 'Stap 2/2'; 
      ui.stepMsg.textContent = 'Leeg de tank tot minimaal niveau en plaats hem terug. Klik op "Markeer EMPTY".'; 
    } else if (step === 2) { 
      await sendCmd('INFO?'); 
      await delay(200); 
      await sendCmd('CAL EMPTY'); 
      log('CAL EMPTY verstuurd'); 
      await delay(300); 
      await sendCmd('CFG?'); 
      log('Auto-calibratie gereed. Waarden opgeslagen.'); 
      closeSteps(); 
    } 
  }
  
  function backStep() { 
    if (step === 2) { 
      step = 1; 
      ui.stepBack.disabled = true; 
      ui.stepNext.textContent = 'Markeer FULL'; 
      ui.stepBadge.textContent = 'Stap 1/2'; 
      ui.stepMsg.textContent = 'Vul de tank volledig en wacht tot het niveau stabiel is. Klik op "Markeer FULL".'; 
    } 
  }
  
  function cancelSteps() { 
    log('Auto-calibratie geannuleerd.'); 
    closeSteps(); 
  }

  // Bindings
  ui.btnConnect.addEventListener('click', connect);
  ui.btnDisconnect.addEventListener('click', disconnect);
  ui.cmds.forEach(b => b.addEventListener('click', async () => {
    const cmd = b.dataset.cmd;
    // Post-refresh mapping per commando
    const POST_REFRESH = {
      'INFO?': [],
      'CFG?': [],
      'TEST?': [],
      'TEST START': ['TEST?','INFO?'],
      'TEST START PIPE': ['TEST?','INFO?'],
      'TEST START PIPE OUT': ['TEST?','INFO?'],
      'TEST STOP': ['TEST?','INFO?'],
      'TEST FAST': ['TEST?'],
      'CAL FULL': ['INFO?','CFG?'],
      'CAL EMPTY': ['INFO?','CFG?'],
      'CAL CLEAR': ['INFO?','CFG?'],
      'CFG RESET': ['CFG?','INFO?']
    };
    
    // Do not poll INFO? during test; rely solely on test stream
    if (cmd === 'TEST START' || cmd === 'TEST START PIPE' || cmd === 'TEST START PIPE OUT') {
      if (testPollTimer) { 
        clearInterval(testPollTimer); 
        testPollTimer = null; 
      }
      setTestIndicator(true);
      testActive = true;
      lastTestActive = true;
    } else if (cmd === 'TEST STOP') {
      if (testPollTimer) { 
        clearInterval(testPollTimer); 
        testPollTimer = null; 
      }
      setTestIndicator(false);
      testActive = false;
      lastTestActive = false;
      preferTestStream = false;
      currentTestId = null;
      log('Test gestopt via commando - alle indicatoren gereset');
    }
    
    try {
      await sendCmd(cmd);
      
      // Post-refresh flow voor relevantere/consistente UI updates
      const followUps = POST_REFRESH[cmd] || [];
      for (const f of followUps) {
        try {
          await delay(120);
          await sendCmd(f);
        } catch (e) {
          log(`Post-refresh ${f} failed: ${e.message}`, 'warn');
        }
      }

      // Specifieke betrouwbaarheid: bevestig TEST STOP binnen 1s anders retry 1x
      if (cmd === 'TEST STOP') {
        try {
          await delay(800);
          if (testActive === true || lastTestActive === true) {
            log('TEST STOP lijkt niet doorgekomen, probeer opnieuw…', 'warn');
            await sendCmd('TEST STOP');
            await delay(200);
            await sendCmd('TEST?');
            await delay(200);
            await sendCmd('INFO?');
          }
        } catch (e) {
          log('Fallback TEST STOP retry faalde: ' + e.message, 'warn');
        }
      }
    } catch (error) {
      log(`Commando ${cmd} mislukt: ${error.message}`, 'error');
      
      // Als commando mislukt, reset test status als het TEST STOP was
      if (cmd === 'TEST STOP') {
        setTestIndicator(false);
        testActive = false;
        lastTestActive = false;
        preferTestStream = false;
        currentTestId = null;
        log('Test status gereset na mislukt TEST STOP commando');
      }
    }
  }));
  
  ui.btnAutoCal.addEventListener('click', openSteps);
  ui.stepNext.addEventListener('click', nextStep);
  ui.stepBack.addEventListener('click', backStep);
  ui.stepCancel.addEventListener('click', cancelSteps);
  ui.modeExpert.addEventListener('change', applyMode);
  ui.btnCfgReset.addEventListener('click', () => { 
    if (confirm('Weet je zeker dat je de configuratie wilt resetten naar defaults?')) {
      sendCmd('CFG RESET').catch(e => log(`CFG RESET failed: ${e.message}`, 'error'));
    }
  });
  ui.btnExportLog.addEventListener('click', exportLog);

  // Init
  setConn('idle'); 
  setStateBadge('—'); 
  setReadyBadge(null); 
  updateGauge(null);
  setTestIndicator(false);
  
  // Restore mode
  try { 
    ui.modeExpert.checked = (localStorage.getItem('wt_mode') === 'expert'); 
  } catch(e){}
  applyMode();
