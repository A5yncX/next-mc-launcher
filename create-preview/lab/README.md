# Pumpkin × Create 本地实验

在 Pumpkin 的 Java 26.3 服务端导入固定版本 Create for Horizon 的完整方块注册表，复用 `create-engine::kinetics::solve` 实现已有的马达、轴和小齿轮联动。服务端计算这三种零件的转速，用方块实体 `Speed` NBT 推送给客户端并写入世界。不是 WASM 插件，也不运行原版 Create JAR。

只支持 Next MC `v0.1.0-beta.2` 的 Create 0.9.0 客户端（Horizon `9f42064`，Atlas 关闭已验证）和 Java 协议 777；配置阶段核对客户端内容指纹。服务端仅允许 Java 监听环回地址、关闭 Bedrock、使用 `create-lab` 世界名。请从新的空目录启动。**不要用旧存档或给公网使用。**

## 构建与验证（Windows / Bash）

1. 解压 [Pumpkin `eda69440e6369c5f8a05c3f69fc809c40dab93a6`](https://github.com/Pumpkin-MC/Pumpkin/archive/eda69440e6369c5f8a05c3f69fc809c40dab93a6.tar.gz) 至 `research_pumpkin_horizon/.cache/`。补丁引用的 Create `b99cab5` 源码在 `research_create_rust/.create-lab-build/stage/native-crates/create/engine`；换目录时可调整 `crates/pumpkin-core/Cargo.toml` 的本地路径，不能换版本。
2. 用这个 Next MC 客户端启用 Create 进入一次游戏，找到实例下 `.horizon-cache/mod-content/<hash>/`，其中含 `facts.json`、`registries.json`、`items.json`。不同实例可用 `--client-cache` 指定这个目录；脚本独立校验导出表，并使用从该版本实际握手确认的网络指纹。不要提交导出的游戏数据或官方 JAR。
3. 从本仓库根目录运行（本机已有的路径为默认值；迁移时按需替换）：

   ```bash
   ROOT="$PWD"
   LAB="$ROOT/research_pumpkin_horizon/create-core"
   P="$ROOT/research_pumpkin_horizon/.cache/Pumpkin-eda69440e6369c5f8a05c3f69fc809c40dab93a6"
   git -C "$P" apply --check "$LAB/pumpkin-create-lab.patch"
   git -C "$P" apply "$LAB/pumpkin-create-lab.patch"
   python "$LAB/generate_pumpkin_data.py" --pumpkin "$P" # 其它缓存位置另传 --client-cache
   export RUSTUP_TOOLCHAIN=stable CARGO_PROFILE_DEV_DEBUG=0 CARGO_BUILD_JOBS=8
   export CARGO_TARGET_DIR="$ROOT/research_pumpkin_horizon/.cache/core-target"
   export PUMPKIN_MINECRAFT_SERVER_JAR="$ROOT/horizon/.local/minecraft/26.3/jars/server.jar"
   cd "$P"
   cargo run --locked -p pumpkin-codegen -- block item
   cargo build --locked -p pumpkin
   cargo test --locked -p pumpkin-core --lib server_blocks_feed_the_create_solver
   python "$LAB/smoke_core.py" # 找不到本机默认客户端时，传入 --client 和 --resources
   ```

只重生成 `block`、`item`；该 Pumpkin 版本在 Windows 跑完整 codegen 会遇到模板路径分隔符错误。Rust 已在本机的 MSVC stable 1.100.0 编译。`--offline` 可用于依赖已缓存的机器。

脚本会创建新的临时 `create-lab`，启动真实客户端，模拟服务端控制台放置／拆除／装回传动轴，并从各客户端实际收到的 26.3 数据包核对转速。重启后从初始区块包核对原方块状态和持久化的 `Speed`。临时验证产物留在 `research_pumpkin_horizon/.cache/create-core-*`。

本机实测：两端均收到 `32 → 0 → 32 RPM`，各渲染 4800 帧、117 个区块；重启后初始区块包保留三个精确状态，三个方块实体的 `Speed` 均为 32。关闭 Create 的客户端在进入世界前被拒绝。见 [`create-core-smoke.log`](../.cache/create-core-smoke.log)。

范围：只打核心补丁时，创造马达固定 32 RPM；调速见下方追加补丁。服务端三种方块的物理形状暂用玻璃占位。在已加载区块内计算，有读取预算；对大网络尚未做缓存或性能测试。扳手、其它 Create 方块、移动机械未涵盖。

## 玩家放置与预览（追加实验）

使用同一组固定版本。在原始核心补丁之上应用 `pumpkin-create-placement.patch`，在已组装 Create + Atlas 的 Horizon 9f42064 stage 应用 `horizon-create-placement.patch`。如需测试原版纹理，只传入自己下载的 Create 6.0.10 JAR；不附带 JAR。

```bash
S="$ROOT/research_create_rust/.create-lab-build/stage"
(cd "$S" && git apply "$LAB/horizon-create-placement.patch")
(cd "$P" && git apply "$LAB/pumpkin-create-placement.patch")
(cd "$P" && cargo build --locked -p pumpkin)
(cd "$S" && cargo build --locked --profile fast -p horizon-client --target-dir ../game-target)
python "$LAB/smoke_placement.py" # 可选 --create-jar /path/to/create-1.21.1-6.0.10.jar
```

Horizon 只在识别到 Pumpkin Create Lab 时使用共用轴/小齿轮规则显示幽灵方块和方向箭头，并等待服务端状态。普通 `UseItemOn` 仍传原始点击位置、面、命中点、手和序号。Pumpkin 独立计算、沿用方块放置检查并同步落点。马达遵循相邻传动口、视角和潜行的朝向规则，不显示辅助预览。

两个独立 Horizon 客户端已实测：马达朝向相邻轴、沿准星方向延长轴、小齿轮沿轴安装和边缘啮合、Shift 跳过辅助落到点击面、首选端被挡时选另一端（生存模式只扣一根轴）。六个右键放置的状态都在重启后重新载入。控制台只用于布置测试夹具；实际放置由客户端走正常右键流程。见 [联机日志](../.cache/placement-acceptance.log)、[轴预览](../.cache/create-placement-08llro33/shaft-preview.png)、[小齿轮预览](../.cache/create-placement-08llro33/cog-preview.png)。

和 Java 6.0.10 的对照目前基于[源码和内嵌 Ponder](placement-parity.md)，不是两个运行实例的逐帧对照。大齿轮、副手、含水、跨区块长轴链等场景未做实机验收。

## 创造马达调速（追加实验）

在上面的服务端放置补丁之后应用 `pumpkin-create-motor.patch` 并重新构建 Pumpkin。不需要重编 Horizon。对准马达侧面的速度刻度，按住右键打开面板，选择速度与方向后松开。服务端仅接受马达调速消息，检查目标和交互距离，重新计算轴与齿轮的转速；设置 `ScrollValue` 与实际转速 `Speed` 分开保存。旧实验世界没有设置时沿用 32 RPM。

```bash
(cd "$P" && git apply "$LAB/pumpkin-create-motor.patch" && cargo build --locked -p pumpkin)
(cd "$P" && cargo test --locked -p pumpkin-core --lib create_kinetic::tests)
python "$LAB/smoke_motor.py" # 可选 --create-jar /path/to/create-1.21.1-6.0.10.jar
```

[联机实测](../.cache/motor-final.log)：从马达面板调至 `+64` 再调至 `−96 RPM`，两端都收到轴和齿轮的新转速；重启后从初始区块读回 `−96` 的设置与转速。同一实验还验证了普通橡木木板的右键放置和重载。

## 全量方块注册（追加实验）

在马达补丁之后应用 `pumpkin-create-registry.patch`。全量生成器导入 Create for Horizon 0.9.0 的 106 种方块、2,145 个状态、123 个物品及 106 个方块实体类型 ID。84 种方块有独立物品，可以走通用右键放置；其余 22 种是皮带、绳索、活塞头等内部方块，不额外伪造物品。

```bash
(cd "$P" && git apply "$LAB/pumpkin-create-registry.patch")
python "$LAB/generate_full_registry.py" --pumpkin "$P" # 可另传 --client-cache
(cd "$P" && cargo run --locked -p pumpkin-codegen -- block item)
(cd "$P" && cargo build --locked -p pumpkin)
(cd "$P" && cargo test --locked -p pumpkin-world --lib create_full_registry_round_trips)
python "$LAB/smoke_registry.py" # 可另传 --create-jar /path/to/create-1.21.1-6.0.10.jar
```

[验证日志](../.cache/registry-validation-final.log)：2,145 个状态与 123 个物品逐项通过 NBT 写入/读回测试。两个 Horizon 客户端都收到了 106 种方块各一个状态，并实测右键放置了安山岩机壳、大齿轮、水车、置物台、机械压力机和机械泵；服务器重启后，展示区、六个落点和背包物品都保留。

全量注册不等于全量玩法。只应用注册补丁时，齿轮联动、马达调速仍以已有三件套为限。通用放置使用默认状态，局部碰撞暂用导出的外形近似。实时进度与剩余验收见 [方块行为清单](behavior-parity.md)。

## 传动、红石控制与水力（追加实验）

在注册补丁之后依次应用传动、控制、水力补丁。重新生成注册表，让这些部件创建方块实体，再编译服务端。North/South 水流、红石边沿、重启和客户端实际收到的数据均由临时实验世界验证。

```bash
(cd "$P" && for patch in drivetrain controls water; do git apply "$LAB/pumpkin-create-$patch.patch" || exit; done)
python "$LAB/generate_full_registry.py" --pumpkin "$P"
(cd "$P" && cargo run --locked -p pumpkin-codegen -- block item && cargo build --locked -p pumpkin)
for test in drivetrain controls water large_water; do python "$LAB/smoke_$test.py" || break; done
```

[小水车](../.cache/water-smoke-v3.log)：材质同步与水流正转、抵消、反转，重启恢复。 [大水车](../.cache/large-water-smoke-v2.log)：受阻不放置、八部件同步、轴输出 `+4 RPM`、重启恢复，拆一部件后移除整个水车且只掉落一次。

## 材料采掘与原版配方（追加实验）

应用 `pumpkin-create-passive.patch` 后重新运行 `generate_full_registry.py`，codegen 改用 `-- block item tag`。在实验世界中用 `generate_passive_data.py <world>/datapacks/create-passive` 生成数据包，再执行 `datapack enable "file/create-passive"`。数据包取自固定版本的 Rust 移植，不从原版 Create JAR 提取。`smoke_passive.py` 验证全部 24 种材料的普通掉落、四种锌材料的工具等级、三种外壳的斧头掉落，以及两种锌矿的时运和精准采集。`smoke_material_application.py --wrench` 额外验证两种铁板只能潜行回收，生存模式返还一块、创造模式不返还。`smoke_zinc_worldgen.py --baseline <添加锌矿前的服务端>` 验证种子 101 的新存档生成两种锌矿，重启后双端可见。切石按钮索引按配方文件路径、命名空间排序；固定配方包的 4 条合成和 18 条切石均已通过 `smoke_passive_recipes.py` 的实际界面操作和重启验收。`smoke_actuator_cleanup.py` 验证活塞杆和干燥绳索的拆除；`smoke_deployer.py` 验证机械手、传送带、红石锁及物品存档。`smoke_crafter.py` 验证 21 格机械合成、堵塞留存、重启和恰好两个粉碎轮的输出。具体未实现行为见 [逐方块台账](behavior-parity.md)。

## 置物台（追加实验）

接续应用 `pumpkin-create-depot.patch`，重新生成注册表和上面的数据包。`smoke_depot.py` 验证置物台顶面手动放入、交换、重启后取回、拆除时掉落已存物品；漏斗和传送带的自动交互尚未接入。

## 表盘与手摇曲柄（追加实验）

接续应用 `pumpkin-create-gauges.patch`、`pumpkin-create-crank.patch`，按上面的步骤重新生成并构建。`smoke_gauges.py` 验证两种仪表的全部 24 种朝向和轴向组合、正反转、比较器输出、重启后的一件掉落，以及用指南针和机壳合成转速表、两种仪表互换。`pumpkin-create-gauge-placement.patch` 修正仪表使用实际点击面；生存实测可在有轴和无轴两种情况下正确朝向。掉落和三条配方来自 `create-passive` 数据包；更新旧测试世界时，先停服并把旧包移出 `datapacks` 备份，再按上文生成同名新包；无需改存档。另有 Rust 单测验证应力表读数。`smoke_crank.py` 验证右键正转、Shift 右键反转、松手停转、重启不会恢复临时动力，支撑移除时只掉落一个曲柄。

接续应用 `pumpkin-create-chain.patch`。`smoke_chain.py` 双端实测链条连接形态、扳手换轴、两侧模拟红石输入与 `32 → 16 → 50 → 64 RPM` 输出，拆下中间部件会停转，复装和重启后恢复。

## 机械压力机（置物台模式）

接续应用 `pumpkin-create-press.patch`，重新生成注册表和数据包后构建。`smoke_press.py` 双端验证受阻不压制、清除阻挡后逐次压制、32 RPM 应力 256，以及重启后从置物台取回两张铁板。Rust 单测核对输出被占满时不消耗原料。当前支持固定版本的铁、金、铜、黄铜锭压板配方，尚未接入传送带、工作盆、掉落物或自定义压制配方。

## 排液台（手动倒入）

接续应用 `pumpkin-create-drain.patch` 后重新生成并构建。`smoke_drain.py` 双端验证手动倒入水桶和水瓶、返还空容器、拒绝混液与溢出、比较器输出 `10 → 12 → 15`、重启后保留 1500 mB 水。处理传送带货物和输出到管道尚未接入。

## 帆与帆框

接续应用 `pumpkin-create-sails.patch` 后重新生成并构建。`smoke_sails.py` 双端验证同平面装帆和染色、帆框阻挡染色、剪成帆框、生存物品扣减、重启以及染色帆只掉一张白帆。风车组装与输出仍未接入。

## 单格储液罐（手动桶存取）

接续应用 `pumpkin-create-fluid-tank.patch` 后重新生成并构建。`smoke_tank.py` 双端验证 8000 mB 容量、比较器、拒绝混装和重启取回液体。接续 `pumpkin-create-tank-multi.patch` 后，`smoke_tank_multi.py` 双端验证同区块 1×1×2 和 2×2×1 合罐、子罐注液和比较器、扳手窗口和岩浆发光。拆除重启后的控制罐，剩余子罐保留其容量内的 8000 mB。跨区块、瓶子和多格罐经泵路由仍未验收。

## 机械泵（直连两个单格罐）

接续应用 `pumpkin-create-pump.patch`、重新生成并构建。`smoke_pump.py` 双端验证小齿轮带动泵、按泵头方向输送、扳手反向、断开动力停止，以及 1000 mB 水往返输送后重启仍可完整取回。此补丁单独使用时只支持泵两侧直连单格罐。

## 三通管道与机械阀门

接续应用 `pumpkin-create-pipes.patch`，重新生成注册表、数据包并构建。`smoke_pipes.py` 用两个客户端验证生存模式右键放置三通、阀门正转开启和反转关闭、断管停流、接回后恢复、两次各 1000 mB 对半分流，以及重启保留阀位和液量。泵每侧最多 16 格、128 个已加载节点。后续多格罐补丁增加了控制罐寻址；单格罐分流回归已通过；`smoke_tank_multi.py` 验证两个多格罐通过上层接口双向传输 9000 mB，并在重启后取回。开放端、管内流动动画和多泵压力网络仍未接入。

## 磨石、鼓风机与溜槽

接续应用 `pumpkin-create-factory.patch` 后重新生成注册表和数据包，再构建。`smoke_factory.py` 双端验证鼓风机 32 RPM、墙体缩短风程、断电停机，以及磨石把两块安山岩磨成两块圆石并在重启后取回。`smoke_chute.py` 双端验证竖直溜槽的阻塞等待、智能溜槽红石开关、物品数量守恒与容器保存。斜溜槽和智能过滤界面尚未接入；后续风扇处理补丁已通过四种介质的掉落物测试。

## 固定式机械钻头

接续应用 `pumpkin-create-drill.patch`。`smoke_drill.py` 用两个客户端验证 32 RPM 时同步裂纹、破坏与清除动画，一块石头掉一块圆石，不破坏基岩和箱子；重启后重新供能才会继续钻。移动结构上的钻头尚未移植。

## 固定机械锯、粉碎轮与黏性装置

`smoke_saw_tree.py` 双端验证 32 RPM 砍倒三格树干、掉落三根原木、不砍连通但另有根的树，重启后仍不切石头。`smoke_saw_processing.py` 双端验证朝上机械锯把一份安山合金切成六根传动杆，出口受阻时跨重启保留，解除阻塞后全部排出。过滤与移动结构上的锯尚未验证。

粉碎轮双端验证对转成组、掉落物加工与堵塞后重启排出；黏性装置双端验证红石上升沿切换与持久化。`smoke_chassis.py` 双端验证直线底盘放置、三类底盘的默认范围、涂胶与空手潜行清除，以及重启恢复。移动结构和批量调距尚未验收。`smoke_fan_processing.py` 验证风扇四种处理介质及重启续作；`smoke_burner.py` 验证烈焰人燃烧室的燃料、热级、比较器和持久化。`smoke_basin.py` 双端验证漏斗进料、四个纯物品配方、黄铜的真实供热门槛与产物持久化。`smoke_encasing.py` 验证六种部件套壳、扳手断开单侧传动、旋转、拆壳及重启恢复。剩余行为与日志见 [移植台账](behavior-parity.md)。

## 漏斗、机壳配方和龙门架

`smoke_funnel.py` 验证垂直容器传输、黄铜漏斗样本过滤、红石与重启；`smoke_material_application.py` 验证六个生存机壳配方；`smoke_gantry.py` 验证三节滑轨、挂载、静止传动与掉线重连。龙门架的移动装配和漏斗与皮带的交互尚未接入。

`smoke_press_world.py` 双端验证动力冲压机处理地面掉落物：一次冲压只把两个铁锭中的一个变成铁板，两个物品和冲压进度重启后仍正确。`smoke_press_belt.py` 验证水平传送带可在冲压前停机保存，重启通电后只冲压一个铁锭，传送带剩一个铁锭和一块铁板。

`smoke_belt.py --cargo` 验证同区块水平传送带：两端轴连接、受阻不消耗、`32 RPM` 传动；7 个石英作为同一组移动，堵塞时存档保留，清掉障碍后完整输出。坡道、跨区块拓扑、机器接入未验收。

补丁应用后统一生成注册表（含主世界天然锌矿的配置和放置表），再构建服务端：

```bash
(cd "$P" && for patch in lab placement motor registry drivetrain controls water passive depot gauges crank chain press drain sails fluid-tank pump pipes factory tank-multi drill saw crusher-sticker saw-processing chassis fan-processing burner basin encasing funnel material gantry funnel-board belt belt-cargo material-wrench zinc-worldgen stonecutter actuators actuator-cleanup deployer crafter contraption-batch contraption-record press-world press-belt contraption-scene bearing-static gauge-placement bearing-motion windmill windmill-direction clockwork bearing-settings harvester plough portable-storage harvest-crops harvest-plants plough-push harvest-vines; do
  git apply "$LAB/pumpkin-create-$patch.patch" || exit
done)
python "$LAB/generate_full_registry.py" --pumpkin "$P"
(cd "$P" && cargo run --locked -p pumpkin-codegen -- block item tag placed_feature placed_features_generated configured_feature configured_features_generated recipes && cargo build --locked -p pumpkin)
```

## 机械轴承与移动结构

`pumpkin-create-contraption-batch.patch` 在批量写入前检查每格原状态，冲突、越界或重复坐标时整批拒绝。`pumpkin-create-contraption-record.patch` 在同一批次核验并替换移动结构记录，方块和记录一起保存。`cargo test --locked -p pumpkin-world --lib chunk::tests` 覆盖拒绝不留部分改动、两种区块存档格式恢复记录并还原方块。当前只覆盖同一区块。`pumpkin-create-contraption-scene.patch` 从区块保存的 `create:contraption_scene` 读取同一代的几何与姿态，用 `horizon:attachment_sync` 紧跟对应区块包发送。`smoke_scene_snapshot.py` 用两个实际 Horizon 客户端验证中心区块与周边流式区块；测试预置的是空场景快照，不代表结构已经能移动。`smoke_bearing_static.py` 验证三种轴承的生存放置和重启，机械轴承与时钟轴承双端收到 32 → 0 → 32 RPM。`smoke_overstress.py` 验证小水轮带粉碎轮时的真实过载、比较器和重启恢复。

`pumpkin-create-bearing-motion.patch` 增加机械轴承装配与停靠；Horizon 客户端在已经应用放置补丁的同一 Create 源码上接续应用 `horizon-create-bearing-motion.patch` 后重建。`smoke_bearing_motion.py` 以两台真实客户端验证：32 RPM 下装配黏液块与安山岩、同步实时姿态、拒绝捕获箱子、停靠受阻后保留结构及原角度，重启后清除障碍即可按最近直角复原。当前只支持同一区块和少量普通方块，不支持跨区块、胶水连接、运动中的碰撞或机器动作。

`pumpkin-create-windmill.patch` 复用上述场景同步。`smoke_windmill.py` 验证 7 片不启动、8 片在双端产生 +1 RPM 和 512 SU，停服重启仍转动，拆解后原位恢复每片帆的朝向。`pumpkin-create-windmill-direction.patch` 接入原有设置面板：运行中从 +1 切换到 −1 RPM，两端保持 512 SU，重启保留方向。当前最多 64 个方块，只支持同一区块，不包含运动碰撞。

`pumpkin-create-clockwork.patch` 接入钟表轴承双指针。`smoke_clockwork.py` 验证两端实际渲染小时、分钟的独立姿态，原有设置面板可交换指针并切换 24 小时制，且两端随世界时间更新。停靠任一手臂受阻时保留两组所有权，重启后清掉障碍才同时复原。目前仅手动装配、同一区块、少量普通方块。启用 `CREATE_TRACE_CONTRAPTION_FRAMES=1` 可额外检查两端渲染轨迹。

`pumpkin-create-bearing-settings.patch` 接入机械轴承的三种停机设置。`smoke_bearing_settings.py` 用实际面板验证归位模式在远离起点时停留、永不放置模式重启后仍保留结构，以及默认模式断电时自动放回方块且不复制载荷。

`pumpkin-create-harvester.patch` 接入竖直机械轴承上的干燥收割机；`pumpkin-create-harvest-crops.patch` 扩展至小麦、胡萝卜、马铃薯、甜菜、下界疣、甜浆果和可可。`smoke_harvester.py` 双客户端验证成熟状态、保留一份复种材料、未成熟小麦不变、甜浆果复位到 age 1、可可保留朝向并产出两份豆。重启保留工具、移动记录及可可产物；拆卸按停靠角度恢复工具朝向。`pumpkin-create-harvest-plants.patch` 另验证蒲公英、虞美人、橡树苗、白桦树苗、树叶剪切掉落及幼年甘蔗各一份。`pumpkin-create-harvest-vines.patch` 继续覆盖缠怨藤、垂泪藤、洞穴藤和海带，双客户端确认海带产物及水源恢复。暂不覆盖含水工具、收纳掉落物及其他载体。

`pumpkin-create-plough.patch` 复用同一移动记录，原子检查地表和土壤后耕地。`smoke_plough.py` 验证双客户端看到裸土耕作、根缠泥土只掉落一份垂根、被覆盖的土不变，以及重启和旋转拆卸。`pumpkin-create-plough-push.patch` 另复用原版速度公式；双客户端看到静止的猪沿犁的移动方向被推动，且重启、拆卸仍通过。尚未实现切割杂草或其他载体。

`pumpkin-create-portable-storage.patch` 接入固定式便携存储接口；`smoke_portable_storage.py` 验证原配方、生存放置、红石状态双客户端同步、重启和单次掉落。尚未接入移动端对接或物品传输；现有场景写入不能原子转移方块实体数据，因此暂不允许捕获接口。
