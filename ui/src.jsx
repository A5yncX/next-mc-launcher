import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Button} from '@astryxdesign/core/Button';
import {IconButton} from '@astryxdesign/core/IconButton';
import {SegmentedControl, SegmentedControlItem} from '@astryxdesign/core/SegmentedControl';
import {Switch} from '@astryxdesign/core/Switch';
import {Theme} from '@astryxdesign/core/theme';
import {matchaTheme} from '@astryxdesign/theme-matcha/built';
import '@astryxdesign/core/reset.css';
import '@astryxdesign/core/astryx.css';
import '@astryxdesign/theme-matcha/theme.css';
import './app.css';

const live = typeof window.ipc?.postMessage === 'function';
const initial = {ready: false, busy: live, cancellable: false, maximized: false, instances: [], selected: 0, progress: {
  phase: live ? 'check' : 'error',
  message: live ? '正在检查已准备的资源…' : '浏览器预览。请打开桌面启动器使用本机资源。',
}};
const pages = [['start', '启动', 'play'], ['instances', '实例', 'stack'], ['download', '下载', 'download'], ['settings', '设置', 'gear']];
const themes = {system: '跟随系统', light: '浅色', dark: '深色'};
const themeKey = 'nextmc.theme';
function readTheme() {
  try {
    const theme = localStorage.getItem(themeKey);
    if (Object.hasOwn(themes, theme)) return theme;
  } catch { /* The page still works if storage is unavailable. */ }
  return 'system';
}
const paths = {
  play: 'm9 5 11 7-11 7z', stack: 'm12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5',
  download: 'M12 3v11m-5-5 5 5 5-5M4 15v5h16v-5', gear: 'M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2M12 6a6 6 0 1 0 .01 0Z',
  minus: 'M5 12h14', maximize: 'M6 6h12v12H6z', restore: 'M6 9h9v9H6zM9 9V6h9v9h-3', close: 'm6 6 12 12M6 18 18 6',
};
const labels = {check: '检查资源', verify: '校验文件', download: '官方下载', prepare: '准备资源', login: 'Microsoft 登录', play: '游戏启动', done: '任务完成', error: '需要处理', cancelled: '已取消'};
const sizes = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 1});
const size = n => n >= 1048576 ? `${sizes.format(n / 1048576)} MiB` : `${sizes.format(n / 1024)} KiB`;
const send = (action, fields = {}) => { if (live) window.ipc.postMessage(JSON.stringify({action, ...fields})); };

function Icon({name}) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

function Block({art = false}) {
  return <svg className={art ? 'block-art' : 'block-mark'} viewBox="0 0 200 180" aria-hidden="true">
    <path className="block-grid" d="M1 127h198M1 153h198M25 180l102-87M60 180l102-87M95 180l102-87M0 170l102-87"/>
    <path className="block-shadow" d="m100 111 61 34-61 34-61-34z"/>
    <g className="block-body">
      <path className="block-top" d="m100 13 57 32-57 32-57-32z"/>
      <path className="block-left" d="m43 45 57 32v70l-57-32z"/>
      <path className="block-right" d="m100 77 57-32v70l-57 32z"/>
      <path className="block-detail" d="m72 61 57-32M72 29l57 32M43 69l57 32 57-32M43 92l57 32 57-32M72 61v70m57-70v70"/>
    </g>
  </svg>;
}

function Task({state}) {
  const {progress: p, busy, cancellable, challenge} = state;
  const [announced, setAnnounced] = useState(p.message);
  useEffect(() => { setAnnounced(p.message); }, [p.phase, busy, cancellable]);
  const working = busy && p.phase !== 'play';
  const percent = typeof p.fraction === 'number' ? Math.round(Math.max(0, Math.min(1, p.fraction)) * 100) : null;
  return <section className="task panel" data-error={p.phase === 'error'} aria-labelledby="task-title">
    <div className="section-line"><h2 id="task-title">{labels[p.phase] || '任务状态'}</h2>{working && percent !== null && <span className="mono">{percent}%</span>}</div>
    <p>{p.message}</p><span className="sr-only" role="status">{announced}</span>
    {challenge && <div className="device-code">
      <p>设备码：<strong><code>{challenge.user_code}</code></strong></p>
      <p className="mono">{challenge.verification_uri}</p>
      <Button label="在浏览器打开 Microsoft" variant="primary" clickAction={() => send('open_verification')}/>
    </div>}
    {working && !challenge && <progress aria-label={labels[p.phase] || '操作进度'} max="100" {...(percent === null ? {} : {value: percent})} />}
    {(p.files || p.bytes) && <div className="counts">{p.files && <span>{p.files[0]} / {p.files[1]} 个文件</span>}{p.bytes && <span>{size(p.bytes[0])} / {size(p.bytes[1])}</span>}</div>}
    {working && cancellable && <Button label={p.phase === 'login' ? '取消登录' : '取消操作'} size="sm" clickAction={() => send('cancel')} />}
  </section>;
}

function App() {
  const [state, setState] = useState(initial);
  const [page, setPage] = useState('start');
  const [source, setSource] = useState('');
  const [name, setName] = useState('');
  const [theme, setTheme] = useState(readTheme);
  const main = useRef(null);
  const chooseTheme = value => {
    setTheme(value);
    try { localStorage.setItem(themeKey, value); } catch { /* This window keeps its choice. */ }
  };
  useLayoutEffect(() => {
    main.current.scrollTop = 0;
    main.current.parentElement.scrollTop = 0;
  }, [page]);
  useEffect(() => {
    window.nextMCUpdate = setState;
    send('status');
    return () => { delete window.nextMCUpdate; };
  }, []);
  const {progress: p, ready, busy, maximized, instances, selected, instance_error: instanceError,
    create_enabled: createEnabled = false, create_issue: createIssue, create_installable: createInstallable,
    create_ready: createReady, atlas_enabled: atlasEnabled = false,
    player_name: playerName, player_avatar: playerAvatar, restoring, remembered, account_notice: accountNotice} = state;
  useEffect(() => { if (selected !== 0) setName(''); }, [selected]);
  const instance = instances.find(item => item.id === selected);
  const instanceName = instance?.name ?? '默认实例';
  const launchReady = createEnabled ? createReady : ready;
  const canPlay = live && launchReady && !busy && !!instance;
  const gameRunning = p.phase === 'play';
  const drag = e => { if (e.button === 0) send('window_drag'); };
  const maximize = () => send('window_maximize');

  return <Theme theme={matchaTheme} mode={theme}>
    <div className="shell">
      <header className="topbar">
        <div className="wordmark" onPointerDown={drag} onDoubleClick={maximize}><Block/><span>Next MC <strong>Launcher</strong></span></div>
        <nav aria-label="启动器导航">
          {pages.map(([id, label, icon]) => <div key={id} className="tab" data-current={page === id}>
            <Button label={label} variant={page === id ? 'secondary' : 'ghost'} icon={<Icon name={icon}/>} clickAction={() => setPage(id)} aria-current={page === id ? 'page' : undefined}/>
          </div>)}
        </nav>
        <div className="drag-space" onPointerDown={drag} onDoubleClick={maximize} aria-hidden="true"/>
        <div className="window-controls" role="group" aria-label="窗口控制">
          <IconButton icon={<Icon name="minus"/>} label="最小化" tooltip="最小化" variant="ghost" size="sm" isDisabled={!live} clickAction={() => send('window_minimize')}/>
          <IconButton icon={<Icon name={maximized ? 'restore' : 'maximize'}/>} label={maximized ? '还原' : '最大化'} tooltip={maximized ? '还原' : '最大化'} variant="ghost" size="sm" isDisabled={!live} clickAction={maximize}/>
          <IconButton icon={<Icon name="close"/>} label="关闭窗口" tooltip="关闭窗口" variant="ghost" size="sm" isDisabled={!live} clickAction={() => send('window_close')}/>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar" aria-label="当前实例和启动">
          <div className="profile"><div className="avatar">{playerAvatar ? <img src={playerAvatar} alt="" width="40" height="40"/> : <Block/>}</div><div><h2>{playerName || '离线玩家'}</h2><p>{playerName ? 'Microsoft 已登录' : restoring ? '正在恢复 Microsoft 登录…' : '无需登录 · 单人游戏'}</p></div></div>
          <div className="current"><span className="eyebrow">当前实例</span><strong>{instanceName}</strong><span className="version-line">Minecraft 26.3 · {createEnabled ? '机械动力' : 'Rust 客户端'}</span></div>
          <div className="launch-actions">
            <Button label={gameRunning ? '游戏运行中' : createEnabled ? '离线启动机械动力' : '离线启动游戏'} variant="primary" size="lg" width="100%" icon={<Icon name="play"/>} isDisabled={!canPlay} clickAction={() => send('play')}/>
            {playerName ? <Button label="使用正版账号启动" width="100%" isDisabled={!canPlay || createEnabled} clickAction={() => send('online_play')}/> : <Button label="Microsoft 正版登录" width="100%" isDisabled={!live || busy || restoring} clickAction={() => { setPage('settings'); send('sign_in'); }}/>}
            <Button label="选择实例" width="100%" clickAction={() => setPage('instances')}/>
            <p className="readiness"><span className="dot" data-ready={launchReady} aria-hidden="true"/>{createEnabled ? (createIssue ? '机械动力组件缺失' : createReady ? '机械动力 · 仅离线启动' : '请先准备机械动力资源') : ready ? '26.3 资源已就绪' : busy ? '正在检查或准备资源' : '还未准备 26.3 资源'}</p>
          </div>
        </aside>
        <main id="workspace" ref={main}>
          <div className="page-flow" key={page}>
          {page === 'start' && <>
            <section className="hero" aria-labelledby="hero-title"><div>
              <span className="eyebrow">JAVA EDITION / 26.3</span><h1 id="hero-title">Minecraft 离线单机</h1>
              <p>{createEnabled ? '使用预编译的机械动力客户端。与普通模式分开保存。' : '使用本机的无附加版 Rust 客户端。每个实例有自己的世界存档和设置。'}</p>
            </div><Block art/></section>
            <section className="panel instance-details"><div className="section-line"><h2>实例详情</h2><span className="badge">本地</span></div>
              <p><strong>{instanceName}</strong><span> · {createEnabled ? '已启用机械动力，使用独立的存档和资源。' : '与其他实例共用 26.3 游戏资源。'}</span></p>
              <div className="actions">
                <Button label="打开实例目录" isDisabled={!live || !instance} clickAction={() => send('reveal_instance')}/>
                <Button label="管理游戏资源" clickAction={() => setPage('download')}/>
              </div>
              {instanceError && <p className="error" role="alert">{instanceError}</p>}
            </section>
          </>}
          {page === 'instances' && <section className="panel page-panel" aria-labelledby="instances-title">
            <span className="eyebrow">本机管理</span><h1 id="instances-title">游戏实例</h1><p>切换后，左侧「启动游戏」会使用选中的实例。原来的存档留在默认实例。</p>
            <form className="create" onSubmit={e => { e.preventDefault(); if (name.trim()) send('create_instance', {name}); }}>
              <div><label htmlFor="instance-name">新实例名称</label><input id="instance-name" value={name} onChange={e => setName(e.target.value)} maxLength={64} placeholder="例如：生存世界" disabled={!live || busy}/></div>
              <Button label="创建实例" type="submit" variant="primary" isDisabled={!live || busy || !name.trim()}/>
            </form>
            {instanceError && <p className="error" role="alert">{instanceError}</p>}
            <ul className="instance-list" aria-label="可用实例">
              {instances.map(item => <li key={item.id}>
                <div><strong>{item.name}</strong><p>{item.id === 0 ? '保留原有存档' : '独立存档和设置'} · 26.3</p></div>
                {item.id === selected ? <span className="badge">当前实例</span> : <Button label={`选用 ${item.name}`} size="sm" isDisabled={busy} clickAction={() => send('select_instance', {id: item.id})}/>}
              </li>)}
            </ul>
            {!instances.length && <p>没有可用实例，请查看任务状态。</p>}
            <Button label="打开实例目录" isDisabled={!live || !instance} clickAction={() => send('reveal_instance')}/>
            {instance && <section className="create-option" aria-label="当前实例的可选模组">
              <p className="eyebrow">{instanceName} · 可选模组</p>
              {createInstallable && <Button label={createIssue ? '安装 Create + Atlas' : '检查 / 修复 Create + Atlas'} isDisabled={!live || busy} clickAction={() => send('install_create')}/>}
              <Switch label="机械动力（Create）" value={createEnabled} isDisabled={!live || busy || (!!createIssue && !createEnabled)}
                onChange={enabled => send('set_create', {id: selected, enabled})}/>
              <p className="hint">仅离线启动。与普通模式分开存档，关闭不会删档。开关打开后前往「下载」准备机械动力资源。</p>
              {createIssue && <p className="hint" role="status">{createIssue}</p>}
              <Switch label="Atlas 小地图和世界地图" value={atlasEnabled} isDisabled={!live || busy || !createEnabled || (!!createIssue && !atlasEnabled)}
                onChange={enabled => send('set_atlas', {id: selected, enabled})}/>
              <p className="hint">{createEnabled ? '按实例保存，默认关闭。开启后游戏内按 M 打开全屏地图。' : '启用机械动力后可开启 Atlas。'}</p>
            </section>}
          </section>}
          {page === 'download' && <section className="panel page-panel" aria-labelledby="resources-title">
            <span className="eyebrow">Minecraft 26.3</span><h1 id="resources-title">游戏资源</h1>
            <p>正在管理{createEnabled ? '机械动力' : '普通模式'}资源。优先复用正版安装文件；只有点「下载缺失文件」才向 Mojang 下载。</p>
            <label htmlFor="source">本机 Minecraft 目录 <span>（可选）</span></label>
            <input id="source" aria-describedby="source-hint" value={source} onChange={e => setSource(e.target.value)} placeholder="例如 D:\Minecraft\.minecraft" maxLength={1024} disabled={busy}/>
            <p className="hint" id="source-hint">留空会查找默认 Minecraft 和 Horizon 安装目录。</p>
            <div className="actions">
              <Button label="检查并准备本机文件" isDisabled={!live || busy} clickAction={() => send('prepare', {source})}/>
              <Button label={p.phase === 'error' || p.phase === 'cancelled' ? '下载缺失文件 / 重试' : '下载缺失文件'} variant="primary" isDisabled={!live || busy || launchReady} clickAction={() => send('download', {source})}/>
            </div>
          </section>}
          {page === 'settings' && <section className="panel page-panel" aria-labelledby="settings-title">
            <span className="eyebrow">启动器</span><h1 id="settings-title">设置</h1>
            <div className="settings-row"><div><strong>界面主题</strong><p>选择会保存在这台电脑上。</p></div>
              <SegmentedControl label="界面主题" size="sm" value={theme} onChange={chooseTheme}>
                {Object.entries(themes).map(([value, label]) => <SegmentedControlItem key={value} value={value} label={label}/>)}
              </SegmentedControl>
            </div>
            <div className="settings-row"><div><strong>本地数据</strong><p className="mono">%LOCALAPPDATA%\NextMC</p></div><Button label="打开数据目录" isDisabled={!live} clickAction={() => send('reveal')}/></div>
            <section className="account-settings" aria-labelledby="account-title">
              <h2 id="account-title">Microsoft 正版登录</h2>
              {playerName ? <div className="settings-row">
                <div><strong>{playerName}</strong><p>已验证 Java 版所有权。{remembered ? '下次打开时会自动恢复登录。' : '本次登录仅在当前窗口有效。'}</p></div>
                <Button label="退出 Microsoft 登录" isDisabled={busy} clickAction={() => send('sign_out')}/>
              </div> : <div className="settings-row">
                <div><p>{restoring ? '正在恢复 Microsoft 登录。此时仍可启动离线单机。' : '在浏览器登录后，当前 Windows 用户会记住账号。共用电脑请在用完后退出登录。'}</p></div>
                <Button label="开始 Microsoft 登录" variant="primary" isDisabled={!live || busy || restoring} clickAction={() => send('sign_in')}/>
              </div>}
              {accountNotice && <p className="hint" role="status">{accountNotice}</p>}
              {!playerName && remembered && !restoring && <Button label="清除本机登录" size="sm" isDisabled={busy} clickAction={() => send('sign_out')}/>}
            </section>
          </section>}
          </div>
          <Task state={state}/>
        </main>
      </div>
    </div>
  </Theme>;
}

createRoot(document.getElementById('root')).render(<App />);
