  // UUID's
  const UART_SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
  const UART_RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'; // write
  const UART_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'; // notify

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
  let reconnectTimer = null;
  let testPollTimer = null;
  let isExpert = false;
  let lastState = null, lastPct = null, lastReady = null;
  let testActive = false;

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

  function exportLog(){
    const lines = Array.from(ui.log.children).reverse().map(n => n.textContent);
    const blob = new Blob([lines.join('\n')], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'watertank_log.txt'; a.click();
    URL.revokeObjectURL(url);
  }

  function setConn(state) {
    ui.connBadge.textContent = state;
    ui.connBadge.className = 'badge ' + (state === 'connected' ? 'b-green' : 'b-gray');
    updateConnButtons(state === 'connected');
  }

  function updateConnButtons(isConnected){
    ui.btnConnect.disabled = !!isConnected;
    ui.btnDisconnect.disabled = !isConnected;
  }

  function setStateBadge(st) {
    const map = { OK: 'b-green', LOW: 'b-yellow', BOTTOM: 'b-red', FAULT: 'b-red' };
    ui.stateBadge.textContent = st || '—';
    ui.stateBadge.className = 'badge ' + (map[st] || 'b-gray');
    ui.lvlFill.className = '';
    if (st === 'OK') ui.lvlFill.classList.add('tone-green');
    else if (st === 'LOW') ui.lvlFill.classList.add('tone-yellow');
    else if (st === 'BOTTOM') ui.lvlFill.classList.add('tone-red');
  }
  function setUserHint(state, pct, ready){
    let txt = '—';
    let boxClass = 'user-hint';
    let dotClass = 'uh-dot';
    if (ready === false) { txt = 'Initialiseren…'; boxClass += ' uh-ok'; dotClass += ' ok'; }
    else if (state === 'OK') { txt = 'Niveau OK'; boxClass += ' uh-ok'; dotClass += ' ok'; }
    else if (state === 'LOW') { txt = 'Niveau laag — vul de tank bij'; boxClass += ' uh-low'; dotClass += ' low'; }
    else if (state === 'BOTTOM') { txt = 'Tank leeg — machine beveiligd. Vul de tank.'; boxClass += ' uh-bottom'; dotClass += ' bottom'; }
    else if (state === 'FAULT') { txt = 'Sensorstoring — controleer sensor/verbinding'; boxClass += ' uh-fault'; dotClass += ' fault'; }
    ui.userHint.textContent = txt;
    ui.userHintBox.className = boxClass;
    ui.userHintDot.className = dotClass;
  }
  function setReadyBadge(val) {
    if (val === null || val === undefined) { ui.readyBadge.textContent = '—'; ui.readyBadge.className = 'badge b-gray'; return; }
    const r = !!val;
    ui.readyBadge.textContent = r ? 'ready' : 'not-ready';
    ui.readyBadge.className = 'badge ' + (r ? 'b-green' : 'b-gray');
  }

  function updateGauge(pct) {
    const v = (typeof pct === 'number') ? Math.max(0, Math.min(100, pct)) : null;
    ui.pct.textContent = (v == null) ? '—' : v.toFixed(1) + '%';
    ui.lvlFill.style.width = (v == null) ? '0%' : v + '%';
  }

  function setTestIndicator(on){
    testActive = !!on;
    if (testActive && !isExpert) ui.testIndicatorRow.classList.remove('hidden');
    else ui.testIndicatorRow.classList.add('hidden');
  }

  function* extractJson(stream){ let d=0,s=-1; for(let i=0;i<stream.length;i++){ const c=stream[i]; if(c==='{' ){ if(d===0) s=i; d++; } else if(c==='}'){ d--; if(d===0 && s!==-1){ yield stream.slice(s,i+1); s=-1; } } } }

  function enableCmds(on) { ui.cmds.forEach(b => b.disabled = !on); ui.btnAutoCal.disabled = !on; }
  function applyMode(){
    isExpert = !!ui.modeExpert.checked;
    // persist
    try { localStorage.setItem('wt_mode', isExpert ? 'expert' : 'user'); } catch(e){}
    // toggle expert-only sections, maar respecteer de 'hidden' van het stappenpaneel
    document.querySelectorAll('.expert').forEach(el => {
      if (el.id === 'stepsPanel') return; // beheerd via open/closeSteps
      if (isExpert) el.classList.remove('hidden'); else el.classList.add('hidden');
    });
    // toggle user-only sections
    document.querySelectorAll('.user').forEach(el => {
      if (isExpert) el.classList.add('hidden'); else el.classList.remove('hidden');
    });
    // Bij modewissel de hint updaten met laatste bekende waarden
    setUserHint(lastState, lastPct, lastReady);
    setTestIndicator(testActive);
  }
  async function sendCmd(txt){ if(!rxChar) return; await rxChar.writeValue(new TextEncoder().encode(txt)); log('> '+txt, 'send'); }

  async function setupGatt(){
    const svc = await server.getPrimaryService(UART_SERVICE);
    txChar = await svc.getCharacteristic(UART_TX);
    rxChar = await svc.getCharacteristic(UART_RX);
    await txChar.startNotifications();
    txChar.addEventListener('characteristicvaluechanged', onNotify);
  }

  async function chooseAndConnect(){
    const dev = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: [UART_SERVICE] });
    device = dev; device.addEventListener('gattserverdisconnected', onDisc);
    server = await device.gatt.connect();
    await setupGatt();
    setConn('connected'); enableCmds(true);
    log('Verbonden met ' + (device.name || 'apparaat'));
    sendCmd('INFO?'); sendCmd('CFG?');
    if (reconnectTimer) { clearInterval(reconnectTimer); reconnectTimer = null; }
  }

  async function connect(){
    try{
      // Als we al een device hebben, probeer direct te verbinden zonder prompt
      if (device) {
        // Zorg dat disconnect-listener staat
        device.removeEventListener && device.removeEventListener('gattserverdisconnected', onDisc);
        device.addEventListener('gattserverdisconnected', onDisc);
        if (!device.gatt.connected) {
          try {
            server = await device.gatt.connect();
            await setupGatt();
            setConn('connected'); enableCmds(true);
            log('Opnieuw verbonden met ' + (device.name || 'apparaat'));
          } catch (e) {
            // Fallback: device-object ongeldig; kies opnieuw via chooser
            log('Herverbinden met bestaand device mislukt, open chooser…', 'warn');
            device = null; server = null; rxChar = null; txChar = null;
            await chooseAndConnect();
            return;
          }
        } else {
          setConn('connected'); enableCmds(true);
        }
        sendCmd('INFO?'); sendCmd('CFG?');
        if (reconnectTimer) { clearInterval(reconnectTimer); reconnectTimer = null; }
        return;
      }
      // Anders: vraag de gebruiker om een device te kiezen (zonder service-filter in advertentie)
      // Sommige firmwares adverteren de service UUID niet in de advertising payload.
      // Gebruik acceptAllDevices + optionalServices om later de UART service te openen.
      await chooseAndConnect();
    }catch(e){ log('Connectie mislukt: ' + (e.message||e), 'error'); }
  }

  async function reconnect(){
    if (!device) return;
    try{
      if (!device.gatt.connected) {
        // Workaround: some browsers need a tiny delay before reconnect
        await delay(150);
        server = await device.gatt.connect();
        await setupGatt();
        setConn('connected'); enableCmds(true);
        log('Opnieuw verbonden met ' + (device.name || 'apparaat'));
        sendCmd('INFO?'); sendCmd('CFG?');
        if (reconnectTimer) { clearInterval(reconnectTimer); reconnectTimer = null; }
      }
    }catch(e){
      log('Reconnect mislukt: ' + (e.message||e), 'warn');
      // blijf proberen in de achtergrond zolang autoReconnect aan staat
      if (ui.autoReconnect.checked && !reconnectTimer) reconnectTimer = setInterval(reconnect, 2000);
    }
  }

  async function disconnect(){ try{ if (device && device.gatt.connected) device.gatt.disconnect(); }catch(e){} }

  function onDisc(){
    // Maak karakteristieken ongeldig zodat we bij reconnect alles opnieuw opzetten
    rxChar = null; txChar = null; server = null;
    enableCmds(false);
    setConn('idle');
    log('Bluetooth disconnected', 'warn');
    setTestIndicator(false);
    if (ui.autoReconnect.checked && device){
      if (!reconnectTimer) reconnectTimer = setInterval(reconnect, 2000);
      setTimeout(reconnect, 1000);
    }
  }

  function onNotify(ev){
    buffer += new TextDecoder().decode(ev.target.value);
    for (const js of extractJson(buffer)){
      try{
        const o = JSON.parse(js);
        if ('state' in o) { setStateBadge(o.state); lastState = o.state; }
        if ('pct' in o) { updateGauge(o.pct); lastPct = o.pct; }
        // Extra velden uit firmware tonen
        if ('ready' in o) { setReadyBadge(o.ready); lastReady = o.ready; }
        if ('ema_mm' in o) ui.ema.textContent = (o.ema_mm == null) ? '—' : Number(o.ema_mm).toFixed(1) + ' mm';
        if ('obs_min' in o || 'obs_max' in o) {
          const mn = (o.obs_min == null) ? '—' : Number(o.obs_min).toFixed(1);
          const mx = (o.obs_max == null) ? '—' : Number(o.obs_max).toFixed(1);
          ui.obs.textContent = mn + ' / ' + mx;
        }
        // Update user hint op basis van laatste bekende state
        setUserHint(lastState, lastPct, lastReady);
        // Test events/status
        if (o.evt === 'test') {
          log('TEST: ' + (o.msg || JSON.stringify(o)), 'warn');
        }
        if (o.evt === 'sys') {
          log('SYS: ' + (o.msg || JSON.stringify(o)) + (o.err ? (' err=' + o.err) : ''), 'warn');
        }
        if ('test_active' in o) {
          const active = !!o.test_active;
          log('TEST active: ' + (active ? 'yes' : 'no'));
          // Start/stop fallback polling tijdens testmodus
          if (active && !testPollTimer) {
            testPollTimer = setInterval(() => { if (rxChar) sendCmd('INFO?'); }, 1000);
          } else if (!active && testPollTimer) {
            clearInterval(testPollTimer); testPollTimer = null;
          }
          setTestIndicator(active);
        }
        // Toon expliciet CFG en INFO responses in het paneel (ook als er 'state' in zit)
        const isCfg = ('uart_port' in o) || ('uart_rx' in o) || ('uart_tx' in o)
          || ('min_mm' in o) || ('max_mm' in o) || ('timeout_ms' in o) || ('sample_hz' in o)
          || ('hysteresis_pct' in o) || ('low_pct' in o) || ('bottom_pct' in o)
          || ('allow_pump_at_low' in o) || ('interlock_active' in o) || ('use_pump_ok' in o) || ('use_heater_ok' in o)
          // Also treat BLE identity fields as CFG so we always render the config dump
          || ('ble_enabled' in o) || ('ble_name' in o);
        const isInfo = ('cal_empty_mm' in o) || ('cal_full_mm' in o);
        if (isCfg || isInfo) {
          try {
            ui.cfgDump.textContent = JSON.stringify(o, null, 2);
          } catch (e) {
            ui.cfgDump.textContent = String(o);
          }
          log('CFG/INFO ontvangen');
        }
      }catch{}
    }
    const lc = buffer.lastIndexOf('}');
    const lo = buffer.lastIndexOf('{');
    if (lc > -1 && lc > lo) buffer = buffer.slice(lc + 1); else if (buffer.length > 2048) buffer = buffer.slice(-1024);
  }

  // Inline Auto-Cal flow
  let step = 0; // 0=closed, 1=FULL, 2=EMPTY
  function delay(ms){ return new Promise(r=>setTimeout(r, ms)); }
  function openSteps(){ if(!rxChar){ log('Niet verbonden', 'warn'); return; } step = 1; ui.stepsPanel.classList.remove('hidden'); ui.stepBack.disabled = true; ui.stepNext.textContent = 'Markeer FULL'; ui.stepBadge.textContent = 'Stap 1/2'; ui.stepMsg.textContent = 'Vul de tank volledig en wacht tot het niveau stabiel is. Klik op “Markeer FULL”.'; enableCmds(false); ui.btnAutoCal.disabled = true; }
  function closeSteps(){ step = 0; ui.stepsPanel.classList.add('hidden'); enableCmds(true); }
  async function nextStep(){ if(step===1){ await sendCmd('INFO?'); await delay(200); await sendCmd('CAL FULL'); log('CAL FULL verstuurd'); step=2; ui.stepBack.disabled=false; ui.stepNext.textContent='Markeer EMPTY'; ui.stepBadge.textContent='Stap 2/2'; ui.stepMsg.textContent='Leeg de tank tot minimaal niveau en plaats hem terug. Klik op “Markeer EMPTY”.'; } else if(step===2){ await sendCmd('INFO?'); await delay(200); await sendCmd('CAL EMPTY'); log('CAL EMPTY verstuurd'); await delay(300); await sendCmd('CFG?'); log('Auto-calibratie gereed. Waarden opgeslagen.'); closeSteps(); } }
  function backStep(){ if(step===2){ step=1; ui.stepBack.disabled = true; ui.stepNext.textContent = 'Markeer FULL'; ui.stepBadge.textContent = 'Stap 1/2'; ui.stepMsg.textContent = 'Vul de tank volledig en wacht tot het niveau stabiel is. Klik op “Markeer FULL”.'; } }
  function cancelSteps(){ log('Auto-calibratie geannuleerd.'); closeSteps(); }

  // Bindings
  ui.btnConnect.addEventListener('click', connect);
  ui.btnDisconnect.addEventListener('click', disconnect);
  ui.cmds.forEach(b => b.addEventListener('click', () => {
    const cmd = b.dataset.cmd;
    // Start/stop test fallback poll immediately on user action
    if (cmd === 'TEST START') {
      if (!testPollTimer) testPollTimer = setInterval(() => { if (rxChar) sendCmd('INFO?'); }, 1000);
      setTestIndicator(true);
    } else if (cmd === 'TEST STOP') {
      if (testPollTimer) { clearInterval(testPollTimer); testPollTimer = null; }
      setTestIndicator(false);
    }
    sendCmd(cmd);
  }));
  ui.btnAutoCal.addEventListener('click', openSteps);
  ui.stepNext.addEventListener('click', nextStep);
  ui.stepBack.addEventListener('click', backStep);
  ui.stepCancel.addEventListener('click', cancelSteps);
  ui.modeExpert.addEventListener('change', applyMode);
  ui.btnCfgReset.addEventListener('click', () => { if (confirm('Weet je zeker dat je de configuratie wilt resetten naar defaults?')) sendCmd('CFG RESET'); });
  ui.btnExportLog.addEventListener('click', exportLog);

  // Init
  setConn('idle'); setStateBadge('—'); setReadyBadge(null); updateGauge(null);
  setTestIndicator(false);
  // Restore mode
  try { ui.modeExpert.checked = (localStorage.getItem('wt_mode') === 'expert'); } catch(e){}
  applyMode();
