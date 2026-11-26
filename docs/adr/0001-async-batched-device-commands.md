# Async Batched Device Commands and Publish-Level Error Reporting

**Status:** accepted

We keep the 100 ms `writeDev` **Command Batch** to protect the **Gateway** during multi-light control, add awaitable `Device.async_turn_on()` / `Device.async_turn_off()` alongside the existing synchronous methods for backward compatibility, and treat successful MQTT publishing (`is_connected` and `publish().rc == 0`) as the completion boundary for every **Control Command** while keeping **Status Query** calls non-raising when disconnected.

## Considered Options

- **Drop 100 ms `writeDev` batching and publish synchronously:** Simplest single-API surface, but removes multi-light payload merging when dozens of lights switch simultaneously.
- **Make existing `Device.turn_on()` / `turn_off()` `async` in place:** Avoids dual methods, but breaks downstream synchronous callers (`ha-dali-center` and Home Assistant Core's dependency-only bump PR) before they can migrate.
- **Wait for gateway `*Res` protocol ACKs before resolving commands:** Closer to physical execution, but requires `msgId` correlation tables, timeout tuning, and increases action latency beyond what Home Assistant's `action-exceptions` rule requires.
- **Add symmetric `async_*` wrappers for direct commands (`identify`, `activate`, `Group.turn_on`):** Rejected because direct commands have no batch delay and already raise synchronously on disconnect or publish failure.

## Consequences

- `asyncio` integrations (such as Home Assistant Core `sunricher_dali`) should call `async_turn_on()` / `async_turn_off()` to receive errors from both pre-enqueue disconnects and 100 ms flush failures; synchronous `turn_on()` / `turn_off()` remain for legacy/non-async callers without emitting runtime `DeprecationWarning` yet.
- Any **Control Command** invoked while disconnected or when paho returns a non-zero `rc` now raises `DaliGatewayError` instead of failing silently; callers that previously ignored errors must handle `DaliGatewayError`.
- **Status Query** calls (`read_status()`) remain non-raising when disconnected so entity registration is not disrupted.
