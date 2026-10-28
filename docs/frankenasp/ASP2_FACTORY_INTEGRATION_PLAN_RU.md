# FrankenASP: план соответствия расширяемому ASP2 и Factory runtime

**Статус:** план, не реализовано; дата 2026-10-27.
**Исходный FrankenASP P3-3B:** `b342255e536d2b4f57f9bd6072dae439c49aa216`.
**Нормативный стандарт:** [ASP2_PROTOCOL.md](ASP2_PROTOCOL.md) (зеркало TECHO5).
**TECHO5 provider:** `experimental/asp2-calibration-design-20261027`, исходный `c2cf4c1...`.

Этот репозиторий отвечает только за **factory-specific C/Bionic DSP helper**, его независимый native Linux launcher, private profile и installer/manifest. Никакие изменения generic ALSA/ASP2/HA/stock fallback не должны переноситься сюда из TECHO5.

## Доработки в FrankenASP

| Путь | План изменений |
|---|---|
| `tools/external-asp/main.c` | Считать переменный CFG2 в bounded buffer 8192 после HELLO, распарсить TLV, валидировать factory-required MIC/REF и калибровку; отдельно валидировать `PLATFORM_INFO` `0x0003` и для заводского профиля требовать подтверждённую `athena` (одного совпадения строки недостаточно — сверять MIC/REF shape и factory manifest). ACK только при выполненных factory предусловиях. Сохранить 500 ms HELLO / 25 ms IPC-budget и stdout как единственный ASP2 wire. |
| `tools/external-asp/core.h` и `core.c` | Immutable state descriptor; per-captured-slot Q30, raw24 conversion, MIC/REF permutations, signed64 multiply+shift, clipping после единственной калибровки, валидация смены формата/потока. 8-ms native quanta и 20-ms FIFO не менять. |
| `tools/external-asp/factory.c` | Единственный экземпляр vendor `libasp.so`, factory API как раньше; explicit calibration authority и проверка, что internal Calibrator не применил те же gains второй раз. Обязательное независимое сравнение с первой Dev Edition. |
| `tools/external-asp/io.c` | Bounded reads/writes for TLV, file integrity in private chroot; fd traversal and permissions of helper-owned profile/assets, no symlink paths. |
| `tools/external-asp/build.sh` / `start32.S` | C native + ARM32/Bionic builds; re-check ELF32, interpreter `/system/bin/linker`, `DT_NEEDED`, GLIBC/TEXTREL, reproducible SHA and known vendor assets. |
| Новый `tools/external-asp/launcher-linux.c` (имя проектное) | Минимальный статический Linux ELF, получает pinned deployment directory FD от TECHO5, читает profile/rootfs через `openat`, создаёт private mount namespace, проверяет mount propagation, подключает оригинальный `/vendor` RO, подготовленный Bionic /system, безопасно делает `chroot+exec` factory helper. Ни одного долгоживущего промежуточного процесса. |
| Новый `tools/external-asp/installer.py` или расширение существующего owner-installer | Устанавливать только `/data/techo5-linux/external-asp/{bin,etc,lib}`: root-owned no group/other writable для нашего дерева. Не chmod/chown `/data` или `/data/techo5-linux`. Никакого global bind, remount stock, публикации factory файлов. |
| `tools/external-asp/tests/test_bridge.py`, `tests/backend.c`, `tests/replay_harness.c` | Golden vectors из TECHO5, калибровка целиком/частично/нет, unknown TLV, failure status, q30 bitwise replay/permutation/clip, short I/O, ASAN/UBSAN when applicable, 100k IPC stress, 5k genuine aged ticks. |
| `tools/external-asp/README.md` и `docs/frankenasp/*` | Factory profile, manifest, owners' recovery, private runtime, installation scope, unpublished production gating and how to implement calibration provider. Ссылка на нормативный ASP2 в этом каталоге. |

## Заводская калибровка — один authority

Принимая универсальный TLV, предлагаю первым реализовать **вариант B**:

1. TECHO5 сообщает настоящие owner-only factory mic Q30 в MIC_FACTORY_GAIN (captured slot order); отправляемые raw MIC и REF неизменны.
2. Наш C-helper читает Q30 из CFG2 и применяет ровно одно умножение после unpack HIGH24/LOW24 и до передачи native [mic0..3,ref0..1] в `asp_process`. Калибровать каналы надо по исходному captured index **до** применения соответствующего MIC permutation, либо математически эквивалентно переставить коэффициенты. REF не калибруется.
3. У внутреннего Amazon Calibrator в изолированном runtime `/proc/idme/miccal.*` **нет**, как в первой реально работавшей Dev Edition, где vendor применял unity fallback. Нельзя предлагать одновременно TLV Q30 и real-proc/idme; это двойная калибровка. `/proc` для Bionic в private chroot может оставаться полноценным procfs, без fake IDME.
4. Если verified complete gains недоступны, profile требует explicit REJECT production. У generic helper такого требования нет.
5. До production сравнить owner-private captured replay старой схемы Go-Q30+vendor-unity и новой C-Q30+vendor-unity; отдельно исследовать отличия от factory-internal Calibrator. При большом отклонении рассмотреть вариант A (Calibrator authentic IDME) как специальный factory-only режим, не меняя универсального ASP2.
6. Клиентские способы корректировки коэффициентов оставить в отдельном **helper profile**, не в заводском IDME и не в стандартном TECHO5.

Это ещё **проект выбора**, а не опубликованное или запущенное решение. Existing P3-3B production REJECT524 сохранять до native-qualification.

## Одна папка на Echo, не менять mainstream

~~~text
/data/techo5-linux/external-asp/          # only our files, root:root 0700
├── bin/
│   └── external-asp                      # native Linux pinned-FD launcher
├── etc/
│   ├── profile.conf                      # private, immutable per session
│   └── assets.sha256                     # verified owner-local system + original vendor
└── lib/
    └── rootfs/
        ├── system/bin/linker             # restored from own factory backup
        ├── system/lib/...                # exact original Bionic/VNDK dependency closure
        ├── vendor/                       # real /vendor readonly bind inside private mount namespace
        ├── proc/                         # procfs for Bionic; NO /proc/idme in variant B
        └── opt/external-asp/factory.bin  # already implemented ARM32/Bionic factory helper
~~~

Ownership/private modes apply to **our tree only**. Stock `/data` and
`/data/techo5-linux` remain 0777 by mainstream policy. No Bionic
assets can appear in public repository, git bundle, CI output or release.

Launcher execution security is **owned by TECHO5**; FrankenASP consumes
the verified exec FD and directory FD. It MUST NOT re-open the
mutable absolute deployment pathname instead of the pinned directory.
Launcher child receives profile and runtime through owned `openat` and
can `fchdir` to pinned rootfs FD before `chroot(".")` to avoid
parent-substitution races. If privilege/namespace/mount isolation fails,
exit without altering global mounts. Parent handles stock fallback.
The loaded factory PIE still sees `/system/bin/linker` inside chroot.

## Explicit stage gates

**F1 — Generic protocol:** shared ASP2 golden conformance, `PLATFORM_INFO` positive/negative/missing/inferred/mismatched and new C parser, legacy 40-byte reject. Universal test helper accepts a syntactically valid unknown platform when real streams are supported; factory Athena helper rejects incompatible platform.

**F2 — C gain pipeline:** Q30/bit depth/unpack/permutation/clip tests, absent-gain REJECT, no host multiply, no double vendor calibration.

**F3 — Native launcher:** private namespace/chroot and readonly vendor; original loader+all ELF closure by SHA; ABI call succeeds; no invisible helper process, no global filesystem modifications.

**F4 — Real offline ASP:** 500 true vendor replay ticks, 5000 aged ticks, 100k synthetic framing/IPC; preserve data-origin/output-bit0 and standard 500ms+25ms budgets, no fake latency claims for emulator. Compare historical Dev Edition inputs/outputs where possible.

**F5 — Owner-only trial:** freeze source, signed checksums, rollback script, protected staging, explicit DEVICE GO, first short bounded activation and native deadlines, confirm stock can recover without A/B writes. DO NOT perform trial as part of docs-only stage.

## Completion criteria

Two repositories implement the same spec (byte-identical golden vectors and protocol documents), native factory helper uses one documented calibration authority, TECHO5 never adjusts raw PCM, safe root-child exec passes race tests, OEM runtime remains owner-private, stock fallback unchanged. Experimental ABI incompatibility documented clearly. Publishing upstream PR and FrankenASP release deferred pending user approval.
