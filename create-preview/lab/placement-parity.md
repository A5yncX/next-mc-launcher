# Create 6.0.10：放置行为对照

目标：让 Horizon + Pumpkin 的实验版在约定场景里表现得和 Minecraft Java 1.21.1 / NeoForge / Create 6.0.10 一样。本页记录 Java 源码对照与验收矩阵；Rust 已完成的实测请见 [玩家放置与预览](README.md#玩家放置与预览追加实验)。暂未运行 Java 客户端做并排实测。

## 原版基准

- 本地原版 `create-1.21.1-6.0.10.jar` SHA256 `ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a`，主包有 2,692 个 `.class`，不含嵌套库。对应 [Create 公开源码 `ac0c444d`](https://github.com/Creators-of-Create/Create/tree/ac0c444d9828da3453ae8cc65338e8de063286fb)。内嵌 `ponder-neoforge-1.0.82+mc1.21.1.jar` 与 Maven 同版本逐字节一致，SHA256 `0cf4611ad853042b689ac386184c5bbe02950efcffddb49e5f604e82baddb0dc`；放置框架在这个 JAR 的 `net.createmod.catnip.placement`，可用[同版本源码](https://maven.createmod.net/net/createmod/ponder/ponder-neoforge/1.0.82+mc1.21.1/ponder-neoforge-1.0.82+mc1.21.1-sources.jar)。
- `ShaftBlock.useItemOn` 接到轴上的交互后先检查潜行、建造权限和外壳等分支，再走 `PoleHelper.getOffset`。它按**命中点**排列同轴的两个方向，先试较近一端，扫描连续的同轴杆件，从末端找可替换格，继承轴向；达到配置上限或被挡会试另一端。`CEquipment.placementAssistRange` 默认 12，原版延伸手臂属性满足时加 4。
- `CogwheelBlockItem.onItemUseFirst` 根据目标齿轮类别、持有物和命中点选择辅助规则。小齿轮对小齿轮优先在垂直于轴的平面中找相邻可落位格；命中轴心会退出这个辅助分支。大小齿轮存在斜向啮合规则，本实验服尚未注册大齿轮。`CreativeMotorBlock.getStateForPlacement` 主要是相邻传动口、视角与潜行决定朝向，不应给马达人为添加原版没有的预览。
- Catnip `PlacementClient.tick` 按准星射线和主/副手物品选择适用助手，在潜行时跳过。成功后调用 `renderAt`（默认方块预览）并驱动准星方向提示；进入时计数每 tick +1 至 10，失去目标时每 tick -2，透明度平方，箭头朝向按 22.5° 分档。服务端 `PlacementOffset.placeInWorld` 才提交放置和置水状态，触发声音、游戏事件、统计等。

## 实施前的断点

- `research_create_rust/.create-lab-build/stage/crates/horizon-client/src/game/remote.rs:7774,7873-7887` 已传原始点击位置、面、格内命中坐标、手和序号；不是协议没传准星数据。
- `research_create_rust/.create-lab-build/stage/native-crates/create/engine/src/core/placement.rs:91-122` 已有轴/齿轮/马达朝向计算，可以复用。但朝向函数不决定辅助落点，也不画预览。
- `research_pumpkin_horizon/.cache/Pumpkin-eda69440e6369c5f8a05c3f69fc809c40dab93a6/crates/pumpkin-core/src/block/registry.rs:634-697,1188-1213` 的普通放置流程选当前可替换格或点击面邻格；未注册专属放置处理的 Create 方块走默认状态。`research_pumpkin_horizon/create-core/generate_pumpkin_data.py:146-165` 仍用玻璃物理基线。素材导入不改变这些行为和命中形状。

## 第一轮验收：只算右键，不算 `/setblock`

用独立 Java 参考世界与独立 Rust 实验世界，固定版本、位置、视角、左右手、游戏模式和已有方块。对照每次预览帧、目标格、最后的方块状态和消耗量。

| 场景 | 对照项 |
| --- | --- |
| 水平/竖直轴，分别从两端及侧面瞄准 | 准星指示出现、方向切换/消失；延长落格，轴向与命中端一致 |
| 瞄准已有轴链、端点阻塞、达到辅助范围、按 Shift | 同一个替代端或同样回退；无有效候选时不显示辅助预览；保持普通右键行为 |
| 小齿轮瞄准另一小齿轮的边缘和轴心 | 比对预览/回退、径向落位、轴向和是否正确反向传动 |
| 马达面对空地或多组相邻传动口 | 比对视角、潜行、相邻口优先，安装后接入轴链 |
| 生存、副手、目标被占用、重连 | 比对实际扣物数量、无错误放置、两个客户端显示相同状态，重启后保留 |

实施顺序：共用纯选位/朝向规则；Horizon 用于预览、瞄准形状和本地反馈；Pumpkin 从原始交互独立验证并提交，不接收客户端宣称的最终格。沿用放置权限、边界、碰撞与扣物流程。先验最小轴链，再扩到大小齿轮、其他机器、传送带及移动结构等；每项只能按已经核验的范围称为对齐。Java 扩展 JAR、外部 API、Java 世界读写和未验收的跨版本行为不属于这个里程碑。
