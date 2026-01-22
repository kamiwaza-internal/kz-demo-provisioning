#!/usr/bin/env python3
"""
Kamiwaza Login Diagnostic Script

This script tests various aspects of a Kamiwaza deployment to diagnose
login issues. It checks:
1. Network connectivity
2. SSL certificate status
3. API endpoint availability
4. Authentication endpoint
5. Service health
6. Common error conditions

Usage:
    python3 scripts/diagnose_kamiwaza_login.py --url https://3.218.164.211
"""

import argparse
import json
import socket
import ssl
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime


def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_result(test_name, success, message="", details=None):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"\n{status} - {test_name}")
    if message:
        print(f"    {message}")
    if details:
        for line in details:
            print(f"    {line}")


def test_dns_resolution(host):
    """Test if the host can be resolved"""
    try:
        ip = socket.gethostbyname(host)
        print_result("DNS Resolution", True, f"Resolved to {ip}")
        return True, ip
    except socket.gaierror as e:
        print_result("DNS Resolution", False, f"Failed: {e}")
        return False, None


def test_port_connectivity(host, port, timeout=10):
    """Test if we can connect to the port"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            print_result(f"Port {port} Connectivity", True, f"Port {port} is open")
            return True
        else:
            print_result(f"Port {port} Connectivity", False, f"Port {port} is closed (error code: {result})")
            return False
    except Exception as e:
        print_result(f"Port {port} Connectivity", False, f"Connection failed: {e}")
        return False


def test_ssl_certificate(host, port=443):
    """Test SSL certificate"""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                issuer = dict(x[0] for x in cert.get('issuer', []))
                subject = dict(x[0] for x in cert.get('subject', []))
                not_after = cert.get('notAfter')
                print_result("SSL Certificate (Valid)", True, 
                            f"Subject: {subject.get('commonName', 'N/A')}",
                            [f"Issuer: {issuer.get('organizationName', 'N/A')}",
                             f"Expires: {not_after}"])
                return True, "valid"
    except ssl.SSLCertVerificationError as e:
        # Self-signed or invalid cert - common for Kamiwaza deployments
        print_result("SSL Certificate (Self-Signed)", True, 
                    "Self-signed certificate detected (expected for new deployments)",
                    [f"Details: {str(e)[:100]}"])
        return True, "self-signed"
    except Exception as e:
        print_result("SSL Certificate", False, f"SSL error: {e}")
        return False, None


def make_request(url, method="GET", data=None, headers=None, verify_ssl=False):
    """Make HTTP request with optional SSL verification"""
    if headers is None:
        headers = {}
    
    # Create SSL context
    if verify_ssl:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    
    try:
        if data:
            if isinstance(data, dict):
                data = urllib.parse.urlencode(data).encode('utf-8')
            elif isinstance(data, str):
                data = data.encode('utf-8')
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        with urllib.request.urlopen(req, timeout=30, context=context) as response:
            body = response.read().decode('utf-8')
            return {
                'status': response.status,
                'headers': dict(response.headers),
                'body': body,
                'success': True
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode('utf-8')
        except:
            pass
        return {
            'status': e.code,
            'headers': dict(e.headers) if hasattr(e, 'headers') else {},
            'body': body,
            'error': str(e),
            'success': False
        }
    except urllib.error.URLError as e:
        return {
            'status': None,
            'error': str(e.reason),
            'success': False
        }
    except Exception as e:
        return {
            'status': None,
            'error': str(e),
            'success': False
        }


def test_https_reachability(base_url):
    """Test if HTTPS endpoint is reachable"""
    result = make_request(base_url)
    if result['success'] or result.get('status'):
        status = result.get('status', 'N/A')
        print_result("HTTPS Reachability", True, f"Got HTTP {status} response")
        return True, result
    else:
        print_result("HTTPS Reachability", False, f"Error: {result.get('error')}")
        return False, result


def test_login_page(base_url):
    """Test if /login page is accessible"""
    url = f"{base_url}/login"
    result = make_request(url)
    
    if result['success']:
        # Check if it looks like a login page
        body = result.get('body', '')
        has_login_form = 'login' in body.lower() or 'password' in body.lower() or 'username' in body.lower()
        
        print_result("/login Page", True, 
                    f"HTTP {result['status']} - Login page found",
                    [f"Contains login elements: {has_login_form}",
                     f"Response size: {len(body)} bytes"])
        return True, result
    else:
        status = result.get('status')
        error = result.get('error', 'Unknown error')
        if status:
            print_result("/login Page", False, f"HTTP {status}: {error}")
        else:
            print_result("/login Page", False, f"Error: {error}")
        return False, result


def test_api_health(base_url):
    """Test various API health endpoints"""
    endpoints = [
        "/api/health",
        "/health",
        "/api/v1/health",
        "/",
    ]
    
    results = []
    for endpoint in endpoints:
        url = f"{base_url}{endpoint}"
        result = make_request(url)
        status = result.get('status', 'Error')
        if result['success'] or status in [200, 301, 302, 304]:
            results.append((endpoint, True, status))
        else:
            results.append((endpoint, False, status or result.get('error', 'Error')))
    
    # Find any successful endpoint
    success_endpoints = [r for r in results if r[1]]
    if success_endpoints:
        details = [f"{ep}: HTTP {st}" for ep, _, st in results]
        print_result("API Health Endpoints", True, 
                    f"Found {len(success_endpoints)} working endpoint(s)",
                    details)
        return True, results
    else:
        details = [f"{ep}: {st}" for ep, _, st in results]
        print_result("API Health Endpoints", False, 
                    "No health endpoints responding",
                    details)
        return False, results


def test_auth_endpoint(base_url):
    """Test if the auth endpoint exists and responds"""
    url = f"{base_url}/api/auth/token"
    
    # First, test with OPTIONS to see if endpoint exists
    result = make_request(url, method="OPTIONS")
    
    # Now test with empty POST to see what error we get
    result = make_request(url, method="POST", data={}, 
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    status = result.get('status')
    body = result.get('body', '')
    
    if status == 422:
        # Validation error - endpoint exists and works
        print_result("Auth Endpoint (/api/auth/token)", True,
                    "Endpoint exists and requires credentials",
                    [f"HTTP {status}: Validation error (expected)"])
        return True, "exists"
    elif status == 401:
        # Unauthorized - endpoint exists
        print_result("Auth Endpoint (/api/auth/token)", True,
                    "Endpoint exists and requires valid credentials",
                    [f"HTTP {status}: Unauthorized (expected without credentials)"])
        return True, "exists"
    elif status == 200:
        print_result("Auth Endpoint (/api/auth/token)", True,
                    "Endpoint accessible (unusual without credentials)")
        return True, "open"
    elif status == 404:
        print_result("Auth Endpoint (/api/auth/token)", False,
                    "Auth endpoint NOT FOUND - this is the problem!",
                    ["The Kamiwaza backend may not be running",
                     "Check if all services are started"])
        return False, "not_found"
    elif status == 502 or status == 503:
        print_result("Auth Endpoint (/api/auth/token)", False,
                    f"HTTP {status}: Backend unavailable",
                    ["The Kamiwaza API server may not be running",
                     "Check backend container status"])
        return False, "backend_down"
    else:
        error = result.get('error', body[:200] if body else 'Unknown')
        print_result("Auth Endpoint (/api/auth/token)", False,
                    f"Unexpected response: HTTP {status}",
                    [f"Error: {error}"])
        return False, "unknown"


def test_login_credentials(base_url, username="admin", password="kamiwaza"):
    """Test actual login with credentials"""
    url = f"{base_url}/api/auth/token"
    
    data = {
        "username": username,
        "password": password
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    result = make_request(url, method="POST", data=data, headers=headers)
    
    status = result.get('status')
    body = result.get('body', '')
    
    if status == 200:
        try:
            json_body = json.loads(body)
            if 'access_token' in json_body:
                print_result(f"Login Test ({username}/{password})", True,
                            "✅ Authentication successful!",
                            ["Received access_token",
                             f"Token type: {json_body.get('token_type', 'N/A')}"])
                return True, json_body
        except:
            pass
        print_result(f"Login Test ({username}/{password})", True,
                    "Got HTTP 200 but unexpected response format",
                    [f"Body: {body[:200]}"])
        return True, None
    
    elif status == 401:
        try:
            json_body = json.loads(body)
            detail = json_body.get('detail', 'No details')
        except:
            detail = body[:200] if body else 'No details'
        
        print_result(f"Login Test ({username}/{password})", False,
                    "Authentication FAILED - Invalid credentials",
                    [f"Error: {detail}",
                     "",
                     "Possible causes:",
                     "  1. Password was changed after deployment",
                     "  2. Keycloak didn't initialize default user",
                     "  3. Different authentication backend configured"])
        return False, detail
    
    elif status == 400:
        try:
            json_body = json.loads(body)
            detail = json_body.get('detail', body[:200])
        except:
            detail = body[:200]
        print_result(f"Login Test ({username}/{password})", False,
                    "Bad request format",
                    [f"Error: {detail}"])
        return False, detail
    
    elif status == 422:
        print_result(f"Login Test ({username}/{password})", False,
                    "Validation error - request format issue",
                    [f"Body: {body[:300]}"])
        return False, body
    
    elif status == 502 or status == 503 or status == 504:
        print_result(f"Login Test ({username}/{password})", False,
                    f"HTTP {status}: Backend service unavailable",
                    ["The authentication backend (Keycloak) may not be running",
                     "Check container status: docker ps | grep keycloak"])
        return False, f"HTTP {status}"
    
    elif status is None:
        print_result(f"Login Test ({username}/{password})", False,
                    f"Connection error: {result.get('error')}",
                    ["Network connectivity issue or service not running"])
        return False, result.get('error')
    
    else:
        print_result(f"Login Test ({username}/{password})", False,
                    f"Unexpected HTTP {status}",
                    [f"Body: {body[:300]}"])
        return False, body


def test_keycloak_direct(base_url):
    """Test if Keycloak is reachable (if applicable)"""
    # Kamiwaza typically proxies Keycloak through the main URL
    # Try common Keycloak paths
    endpoints = [
        "/auth/realms/kamiwaza",
        "/auth/realms/master",
        "/auth/",
        "/realms/kamiwaza",
    ]
    
    results = []
    for endpoint in endpoints:
        url = f"{base_url}{endpoint}"
        result = make_request(url)
        status = result.get('status')
        if status and status != 404:
            results.append((endpoint, True, status, result.get('body', '')[:100]))
        else:
            results.append((endpoint, False, status or 'Error', ''))
    
    success = any(r[1] for r in results)
    details = [f"{ep}: HTTP {st}" for ep, _, st, _ in results]
    
    if success:
        print_result("Keycloak Endpoints", True,
                    "Keycloak appears to be accessible",
                    details)
    else:
        print_result("Keycloak Endpoints", False,
                    "Keycloak endpoints not found (may be internal-only)",
                    details)
    
    return success, results


def test_frontend_assets(base_url):
    """Check if frontend is serving correctly"""
    endpoints = [
        "/",
        "/static/",
        "/assets/",
    ]
    
    # Test root URL
    result = make_request(f"{base_url}/")
    status = result.get('status')
    body = result.get('body', '')
    
    if status == 200:
        # Check if it looks like the Kamiwaza frontend
        is_kamiwaza = 'kamiwaza' in body.lower() or 'react' in body.lower() or '<!DOCTYPE' in body
        print_result("Frontend Serving", True,
                    f"HTTP {status} - Frontend accessible",
                    [f"Looks like Kamiwaza UI: {is_kamiwaza}",
                     f"Response size: {len(body)} bytes"])
        return True
    else:
        print_result("Frontend Serving", False,
                    f"HTTP {status or 'Error'}: {result.get('error', '')[:100]}")
        return False


def print_recommendations(results):
    """Print recommendations based on test results"""
    print_header("DIAGNOSIS & RECOMMENDATIONS")
    
    recommendations = []
    
    if not results.get('port_443'):
        recommendations.append({
            'severity': 'CRITICAL',
            'issue': 'Port 443 (HTTPS) is not accessible',
            'fix': [
                '1. Check EC2 Security Group allows inbound port 443',
                '2. Verify the instance is running: aws ec2 describe-instances',
                '3. Check if nginx/reverse proxy is running on the instance'
            ]
        })
    
    if not results.get('auth_endpoint'):
        recommendations.append({
            'severity': 'CRITICAL',
            'issue': 'Authentication endpoint not responding',
            'fix': [
                '1. SSH into the instance and check services:',
                '   ssh -i key.pem ubuntu@3.218.164.211',
                '   kamiwaza status',
                '   docker ps | grep kamiwaza',
                '',
                '2. Check for errors in logs:',
                '   sudo tail -f /var/log/kamiwaza-deployment.log',
                '   sudo tail -f /var/log/kamiwaza-startup.log',
                '',
                '3. Try restarting Kamiwaza:',
                '   kamiwaza restart'
            ]
        })
    
    if results.get('auth_endpoint') and not results.get('login_success'):
        recommendations.append({
            'severity': 'HIGH',
            'issue': 'Login credentials rejected (admin/kamiwaza)',
            'fix': [
                '1. SSH into the instance and check Keycloak status:',
                '   ssh -i key.pem ubuntu@3.218.164.211',
                '   docker ps | grep keycloak',
                '   docker logs $(docker ps -q --filter name=keycloak) --tail 100',
                '',
                '2. Check if Keycloak initialized correctly:',
                '   - Keycloak may need time to initialize',
                '   - Check if kamiwaza realm exists',
                '',
                '3. Reset admin password via Kamiwaza CLI (if available):',
                '   kamiwaza user reset-password admin',
                '',
                '4. Check Kamiwaza database for user:',
                '   docker exec -it kamiwaza-backend bash',
                '   sqlite3 /app/data/kamiwaza.db "SELECT * FROM users;"',
                '',
                '5. Check backend logs for auth errors:',
                '   docker logs $(docker ps -q --filter name=backend) --tail 200'
            ]
        })
    
    if not recommendations:
        print("\n✅ All basic tests passed!")
        if results.get('login_success'):
            print("\n   Login is working. If you're still having issues in the browser:")
            print("   - Clear browser cache and cookies")
            print("   - Try incognito/private window")
            print("   - Check browser console for JavaScript errors")
    else:
        for rec in recommendations:
            print(f"\n🔴 [{rec['severity']}] {rec['issue']}")
            print("   Recommended fixes:")
            for fix in rec['fix']:
                print(f"   {fix}")
    
    # SSH command helper
    print("\n" + "="*60)
    print("  QUICK SSH ACCESS")
    print("="*60)
    print("""
To SSH into the instance for debugging:

  ssh -i YOUR_KEY.pem ubuntu@3.218.164.211

Once connected, useful commands:

  # Check service status
  kamiwaza status

  # Check Docker containers
  docker ps

  # View deployment logs
  sudo tail -f /var/log/kamiwaza-deployment.log

  # View startup logs
  sudo tail -f /var/log/kamiwaza-startup.log

  # Restart Kamiwaza
  kamiwaza restart

  # Check Keycloak logs
  docker logs $(docker ps -q --filter name=keycloak) --tail 100

  # Check backend logs
  docker logs $(docker ps -q --filter name=backend) --tail 100
""")


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose Kamiwaza login issues"
    )
    parser.add_argument(
        "--url",
        default="https://3.218.164.211",
        help="Kamiwaza instance URL (default: https://3.218.164.211)"
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Username to test (default: admin)"
    )
    parser.add_argument(
        "--password",
        default="kamiwaza",
        help="Password to test (default: kamiwaza)"
    )
    
    args = parser.parse_args()
    
    # Parse URL
    base_url = args.url.rstrip('/')
    if not base_url.startswith('http'):
        base_url = f"https://{base_url}"
    
    # Extract host
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    
    print("="*60)
    print("  KAMIWAZA LOGIN DIAGNOSTIC TOOL")
    print("="*60)
    print(f"\nTarget: {base_url}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Testing credentials: {args.username} / {'*' * len(args.password)}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # Run tests
    print_header("1. NETWORK CONNECTIVITY")
    
    # DNS resolution (for IP, this is trivial)
    results['dns'], _ = test_dns_resolution(host)
    
    # Port connectivity
    results['port_443'] = test_port_connectivity(host, 443)
    results['port_80'] = test_port_connectivity(host, 80)
    
    if not results['port_443'] and not results['port_80']:
        print("\n⛔ Cannot reach the instance. Check:")
        print("   - Is the EC2 instance running?")
        print("   - Are Security Groups configured correctly?")
        print("   - Is there a Network ACL blocking access?")
        print_recommendations(results)
        return 1
    
    print_header("2. SSL/TLS CERTIFICATE")
    results['ssl'], ssl_type = test_ssl_certificate(host, port)
    
    print_header("3. HTTP CONNECTIVITY")
    results['https_reachable'], _ = test_https_reachability(base_url)
    results['frontend'] = test_frontend_assets(base_url)
    results['login_page'], _ = test_login_page(base_url)
    
    print_header("4. API ENDPOINTS")
    results['api_health'], _ = test_api_health(base_url)
    results['auth_endpoint'], auth_status = test_auth_endpoint(base_url)
    
    print_header("5. KEYCLOAK (AUTHENTICATION BACKEND)")
    results['keycloak'], _ = test_keycloak_direct(base_url)
    
    print_header("6. LOGIN TEST")
    results['login_success'], login_result = test_login_credentials(
        base_url, args.username, args.password
    )
    
    # Also try alternative credentials
    if not results['login_success']:
        print("\n    Trying alternative common credentials...")
        alt_creds = [
            ("admin", "admin"),
            ("admin", "password"),
            ("admin", "Admin123!"),
        ]
        for alt_user, alt_pass in alt_creds:
            if alt_user != args.username or alt_pass != args.password:
                success, _ = test_login_credentials(base_url, alt_user, alt_pass)
                if success:
                    results['alt_login'] = (alt_user, alt_pass)
                    break
    
    # Print recommendations
    print_recommendations(results)
    
    # Summary
    print_header("SUMMARY")
    passed = sum(1 for v in results.values() if v and v != False)
    total = len(results)
    print(f"\nTests passed: {passed}/{total}")
    
    if results.get('login_success'):
        print("\n✅ LOGIN SHOULD WORK with admin/kamiwaza")
        return 0
    elif results.get('alt_login'):
        user, pwd = results['alt_login']
        print(f"\n✅ LOGIN WORKS with {user}/{pwd}")
        return 0
    else:
        print("\n❌ LOGIN IS NOT WORKING - see recommendations above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
