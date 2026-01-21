# Kamiwaza Deployment Script - Alignment Fixes

## Date
2026-01-20

## Summary
Updated the Kamiwaza deployment implementation to align with official installation instructions provided by the user.

## Official Installation Instructions

The official instructions for installing Kamiwaza from a `.deb` package:

```bash
sudo apt update
wget https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/kamiwaza_v0.9.2_noble_x86_64_build3.deb -P /tmp
sudo apt install -f -y /tmp/kamiwaza_v0xxxxxx.deb
kamiwaza start
```

To remove:
```bash
sudo apt remove --purge kamiwaza
```

## Issues Found in Previous Implementation

### 1. **Wrong Installation Method**
- **Previous**: Used `dpkg -i` with fallback to `apt-get install -f -y`
- **Official**: Use `apt install -f -y /path/to/package.deb` directly
- **Impact**: Minor difference, but not following documented method

### 2. **Never Called `kamiwaza start`** ⚠️ CRITICAL
- **Previous**: Created custom systemd services and manually ran `containers-up.sh` and `launch.sh`
- **Official**: Simply run `kamiwaza start` command
- **Impact**:
  - Bypassed official startup sequence
  - Missing initialization steps from the `.deb` package
  - Custom systemd service may not be compatible
  - Unsupported deployment method

### 3. **Attempted Amazon Linux Support**
- **Previous**: Script tried to support Amazon Linux 2023 by converting `.deb` to `.rpm`
- **Official**: `.deb` packages are for Ubuntu 22.04 or 24.04 ONLY
- **Impact**: Would never work correctly on Amazon Linux

### 4. **Over-Engineered Setup**
- **Previous**: Manual Docker installation, system dependencies, environment file creation, etc.
- **Official**: The `.deb` package handles all dependencies
- **Impact**: Unnecessary complexity, potential conflicts

## Changes Made

### 1. Updated `scripts/deploy_kamiwaza_full.sh`

**Key Changes:**
- Removed all Amazon Linux support (not compatible with `.deb` packages)
- Added OS validation to enforce Ubuntu 22.04 or 24.04 only
- Simplified to follow official 4-step process:
  1. `apt update`
  2. `wget` package to `/tmp`
  3. `apt install -f -y /tmp/package.deb`
  4. `kamiwaza start` (as the specified user)
- Removed custom systemd service creation
- Removed manual Docker installation (handled by `.deb`)
- Removed manual container orchestration
- Removed custom environment file creation
- Reduced script from ~463 lines to ~250 lines

**Script Now Follows:**
```bash
# Step 1: apt update
apt-get update -y

# Step 2: Download package
wget $KAMIWAZA_PACKAGE_URL -P /tmp

# Step 3: Install package
apt install -f -y /tmp/kamiwaza_*.deb

# Step 4: Start Kamiwaza
su - $KAMIWAZA_USER -c "kamiwaza start"
```

### 2. Updated `cdk/app.py`

**Key Changes:**
- Already used Ubuntu 24.04 Noble ✓
- Fixed default user data to use Ubuntu commands (was using Amazon Linux `yum` commands)
- Changed from `yum update` to `apt-get update`
- Improved comments to clarify Ubuntu requirement

## Benefits of New Approach

1. **Official Support**: Uses documented installation method
2. **Simpler**: ~50% reduction in code complexity
3. **Maintainable**: Will continue to work with future Kamiwaza releases
4. **Reliable**: Uses the `kamiwaza start` command which handles all initialization
5. **Clear**: Easy to understand and debug

## Testing Recommendations

Before deploying to production, test the new script:

1. Deploy a test instance:
   ```bash
   python3 deploy_kamiwaza.py --name test-alignment --region us-east-1
   ```

2. Monitor the deployment logs:
   ```bash
   # Get instance ID from outputs
   aws ssm start-session --target <instance-id> --region us-east-1
   sudo tail -f /var/log/kamiwaza-deployment.log
   sudo tail -f /var/log/kamiwaza-startup.log
   ```

3. Verify the login page becomes accessible at `https://<public-ip>`

4. Check that the `kamiwaza` command is available:
   ```bash
   kamiwaza --help
   ```

## Migration Notes

If you have existing deployments using the old script:

1. They will continue to work but are using an unsupported method
2. To migrate, you would need to:
   - Back up any data
   - Terminate old instances
   - Deploy new instances with the updated script
   - Restore data if needed

## References

- Official Kamiwaza Docs: https://docs.kamiwaza.ai/installation/linux_macos_tarball
- Package URL: https://pub-3feaeada14ef4a368ea38717abd3cf7e.r2.dev/kamiwaza_v0.9.2_noble_x86_64_build3.deb
- Supported OS: Ubuntu 22.04 or 24.04 LTS only
