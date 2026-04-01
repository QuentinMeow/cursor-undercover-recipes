# Lessons

## Runtime Sync

- **Long-lived injected scripts need an explicit version handshake**: When a
  launcher can update the on-disk JavaScript while the target window stays
  open, compare an on-disk script hash with the in-window injector state and
  reload only when they differ. Otherwise `status` can look healthy while the
  running window still uses stale logic.
