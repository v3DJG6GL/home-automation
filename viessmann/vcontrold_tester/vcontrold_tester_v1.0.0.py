#!/usr/bin/env python3
"""
vcontrold Tester v1.0.0
===============================================

"""

import socket
import time
import csv
import json
import argparse
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional
import os
import sys
import select

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.columns import Columns
    from rich.align import Align
    from rich import box
    from rich.layout import Layout
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("💡 Install 'rich' for beautiful tables: pip install rich")

class VcontroldCommandDiscoverer:
    """Discovers commands from XML configuration files."""

    def __init__(self, vito_xml_path: str = "vito.xml", vcontrold_xml_path: str = "vcontrold.xml"):
        self.vito_xml_path = vito_xml_path
        self.vcontrold_xml_path = vcontrold_xml_path
        self.logger = logging.getLogger(__name__)

    def discover_commands(self) -> List[Dict]:
        """Discover all GET commands from XML files."""
        commands = []

        if os.path.exists(self.vito_xml_path):
            self.logger.info(f"Discovering commands from {self.vito_xml_path}")
            commands.extend(self._parse_vito_xml())

        if os.path.exists(self.vcontrold_xml_path):
            self.logger.info(f"Checking {self.vcontrold_xml_path} for additional commands")
            commands.extend(self._parse_vcontrold_xml())

        if not commands:
            self.logger.warning("No commands discovered from XML files")
            return []

        # Remove duplicates based on command name
        unique_commands = {}
        for cmd in commands:
            if cmd['name'] not in unique_commands:
                unique_commands[cmd['name']] = cmd

        commands = list(unique_commands.values())
        self.logger.info(f"Discovered {len(commands)} total unique commands")
        return commands

    def _parse_vito_xml(self) -> List[Dict]:
        """Parse vito.xml for command definitions."""
        commands = []

        try:
            with open(self.vito_xml_path, 'r', encoding='utf-8') as f:
                content = f.read()

            root = ET.fromstring(content)

            for command in root.findall('.//command'):
                cmd_name = command.get('name')
                protocmd = command.get('protocmd')

                addr_elem = command.find('addr')
                len_elem = command.find('len')
                unit_elem = command.find('unit')
                desc_elem = command.find('description')

                addr = addr_elem.text if addr_elem is not None else None
                length = len_elem.text if len_elem is not None else None
                unit = unit_elem.text if unit_elem is not None else None
                description = desc_elem.text if desc_elem is not None else None

                # FIXED: Only include GET commands (read-only, safe)
                # Exclude SET commands (can modify heating system settings - dangerous!)
                # Exclude bare protocmd entries like "getaddr", "setaddr"
                if cmd_name and protocmd:
                    # Check if this is a GET command only
                    if cmd_name.lower().startswith('get') and cmd_name not in ['getaddr']:
                        commands.append({
                            'name': cmd_name,
                            'protocmd': protocmd,
                            'addr': addr,
                            'len': length,
                            'unit': unit,
                            'description': description,
                            'source': 'vito.xml'
                        })

            self.logger.info(f"Found {len(commands)} GET commands in vito.xml")

        except Exception as e:
            self.logger.error(f"Error parsing vito.xml: {e}")

        return commands

    def _parse_vcontrold_xml(self) -> List[Dict]:
        """Parse vcontrold.xml for additional command definitions."""
        commands = []

        try:
            with open(self.vcontrold_xml_path, 'r', encoding='utf-8') as f:
                content = f.read()

            root = ET.fromstring(content)

            for command in root.findall('.//command'):
                cmd_name = command.get('name')
                protocmd = command.get('protocmd')

                # FIXED: Only include GET commands (read-only, safe)
                # Exclude SET commands and bare protocmd entries like "getaddr", "setaddr"
                if cmd_name and cmd_name.lower().startswith('get') and cmd_name not in ['getaddr']:
                    commands.append({
                        'name': cmd_name,
                        'protocmd': protocmd if protocmd else 'N/A',
                        'addr': 'N/A',
                        'len': 'N/A',
                        'unit': 'N/A',
                        'description': 'N/A',
                        'source': 'vcontrold.xml'
                    })

            self.logger.info(f"Found {len(commands)} additional commands in vcontrold.xml")

        except FileNotFoundError:
            self.logger.warning(f"vcontrold.xml not found at {self.vcontrold_xml_path}")
        except Exception as e:
            self.logger.error(f"Error parsing vcontrold.xml: {e}")

        return commands

class VcontroldTester:

    def __init__(self, host: str = '127.0.0.1', port: int = 3002, timeout: int = 30,
                 vito_xml: str = "vito.xml", vcontrold_xml: str = "vcontrold.xml",
                 debug: bool = False, simple_mode: bool = False):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.debug = debug
        self.simple_mode = simple_mode
        self.results = []
        self.commands = []
        self.console = Console() if RICH_AVAILABLE else None

        # Setup logging - FIXED: Debug now shows in console too
        log_level = logging.DEBUG if debug else logging.INFO
        log_filename = f'vcontrold_tester_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

        # Create handlers
        file_handler = logging.FileHandler(log_filename)
        file_handler.setLevel(log_level)

        # Console handler for debug output
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if debug else logging.INFO)

        # Format
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Setup logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)
        self.logger.addHandler(file_handler)

        if debug:  # Only add console handler for debug mode
            self.logger.addHandler(console_handler)

        # Discover commands
        discoverer = VcontroldCommandDiscoverer(vito_xml, vcontrold_xml)
        self.commands = discoverer.discover_commands()

        if not self.commands:
            self.logger.error("No commands discovered! Please ensure vito.xml is available.")
            sys.exit(1)

    def test_connection(self) -> bool:
        """Test basic connection to vcontrold daemon."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(30)
                sock.connect((self.host, self.port))

                response = b''
                start_time = time.time()

                while time.time() - start_time < 3:
                    try:
                        chunk = sock.recv(1024)
                        if not chunk:
                            break
                        response += chunk
                        if b'vctrld>' in response:
                            break
                    except socket.timeout:
                        break

                response_str = response.decode('utf-8', errors='ignore')

                if 'vctrld>' in response_str:
                    if RICH_AVAILABLE:
                        self.console.print(f"✓ Connected to vcontrold at {self.host}:{self.port}", style="green")
                    else:
                        print(f"✓ Connected to vcontrold at {self.host}:{self.port}")

                    if self.debug:
                        self.logger.debug(f"Connection response: {repr(response_str)}")
                    return True
                else:
                    if RICH_AVAILABLE:
                        self.console.print(f"✗ No vctrld> prompt received: {response_str}", style="red")
                    else:
                        print(f"✗ No vctrld> prompt received: {response_str}")
                    return False

        except Exception as e:
            if RICH_AVAILABLE:
                self.console.print(f"✗ Connection failed: {e}", style="red")
            else:
                print(f"✗ Connection failed: {e}")
            return False

    def execute_command(self, command: Dict) -> Dict:
        """Execute command with proper timeout that returns immediately when response is complete."""
        cmd_name = command['name']
        start_time = time.time()

        if self.debug:
            self.logger.debug(f"🔍 Executing command: {cmd_name}")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))

                if self.debug:
                    self.logger.debug(f"📡 Connected to {self.host}:{self.port}")

                initial_response = b''
                initial_start = time.time()

                while time.time() - initial_start < 2:
                    try:
                        sock.settimeout(0.1)
                        chunk = sock.recv(1024)
                        if not chunk:
                            break
                        initial_response += chunk
                        if b'vctrld>' in initial_response:
                            if self.debug:
                                self.logger.debug(f"📥 Got initial prompt: {repr(initial_response)}")
                            break
                    except socket.timeout:
                        continue

                cmd_msg = f"{cmd_name}\n"
                if self.debug:
                    self.logger.debug(f"📤 Sending command: {repr(cmd_msg)}")
                sock.sendall(cmd_msg.encode())

                response = b''
                last_data_time = time.time()
                no_data_timeout = 2.0
                got_meaningful_response = False

                if self.debug:
                    self.logger.debug(f"📖 Reading response with timeout (max: {self.timeout}s)")

                while True:
                    elapsed = time.time() - start_time

                    if elapsed >= self.timeout:
                        if self.debug:
                            self.logger.debug(f"⏰ Max timeout reached after {elapsed:.2f}s")
                        break

                    time_since_last_data = time.time() - last_data_time

                    if got_meaningful_response and time_since_last_data >= no_data_timeout:
                        if self.debug:
                            self.logger.debug(f"📭 No new data for {no_data_timeout}s after meaningful response at {elapsed:.2f}s")
                        break

                    try:
                        sock.settimeout(0.1)
                        chunk = sock.recv(1024)

                        if not chunk:
                            if self.debug:
                                self.logger.debug(f"📭 Connection closed by server at {elapsed:.2f}s")
                            break

                        response += chunk
                        last_data_time = time.time()

                        if self.debug:
                            self.logger.debug(f"📥 Received chunk at {elapsed:.2f}s: {repr(chunk)}")

                        response_str = response.decode('utf-8', errors='ignore')

                        lines = [l.strip() for l in response_str.split('\n') if l.strip()]
                        if len(lines) >= 2:
                            got_meaningful_response = True

                        if response_str.strip().endswith('vctrld>') and got_meaningful_response:
                            if self.debug:
                                self.logger.debug(f"✅ Complete response with data received in {elapsed:.2f}s")
                            break

                    except socket.timeout:
                        continue
                    except Exception as e:
                        if self.debug:
                            self.logger.debug(f"❌ Read error: {e}")
                        break

                response_str = response.decode('utf-8', errors='ignore')

                if self.debug:
                    self.logger.debug(f"📄 Full response: {repr(response_str)}")

                result = self._extract_result_from_response(response_str, cmd_name)

                execution_time = time.time() - start_time

                if self.debug:
                    self.logger.debug(f"🎯 Extracted result: {repr(result)}")
                    self.logger.debug(f"⏱️ Total execution time: {execution_time:.3f}s")

                if result is None or result.strip() == '':
                    status = 'NO_DATA'
                    result = 'No data returned'
                elif any(error in result.lower() for error in ['error', 'err:', 'timeout', 'failed', 'invalid', 'unknown command']):
                    status = 'ERROR'
                else:
                    status = 'SUCCESS'

                return {
                    'command': cmd_name,
                    'address': command.get('addr', 'N/A'),
                    'length': command.get('len', 'N/A'),
                    'unit': command.get('unit', 'N/A'),
                    'description': command.get('description', 'N/A'),
                    'status': status,
                    'result': result,
                    'execution_time': round(execution_time, 3),
                    'timestamp': datetime.now().isoformat(),
                    'source': command.get('source', 'unknown')
                }

        except socket.timeout:
            execution_time = time.time() - start_time
            if self.debug:
                self.logger.debug(f"⏰ Socket timeout after {execution_time:.2f}s")

            return {
                'command': cmd_name,
                'address': command.get('addr', 'N/A'),
                'length': command.get('len', 'N/A'),
                'unit': command.get('unit', 'N/A'),
                'description': command.get('description', 'N/A'),
                'status': 'TIMEOUT',
                'result': f'Command timed out after {execution_time:.2f}s',
                'execution_time': round(execution_time, 3),
                'timestamp': datetime.now().isoformat(),
                'source': command.get('source', 'unknown')
            }
        except Exception as e:
            execution_time = time.time() - start_time
            if self.debug:
                self.logger.debug(f"❌ Command execution failed: {e}")

            return {
                'command': cmd_name,
                'address': command.get('addr', 'N/A'),
                'length': command.get('len', 'N/A'),
                'unit': command.get('unit', 'N/A'),
                'description': command.get('description', 'N/A'),
                'status': 'CONNECTION_ERROR',
                'result': str(e),
                'execution_time': round(execution_time, 3),
                'timestamp': datetime.now().isoformat(),
                'source': command.get('source', 'unknown')
            }



        except Exception as e:
            execution_time = time.time() - start_time
            if self.debug:
                self.logger.debug(f"❌ Command execution failed: {e}")

            return {
                'command': cmd_name,
                'address': command.get('addr', 'N/A'),
                'length': command.get('len', 'N/A'),
                'unit': command.get('unit', 'N/A'),
                'description': command.get('description', 'N/A'),
                'status': 'CONNECTION_ERROR',
                'result': str(e),
                'execution_time': round(execution_time, 3),
                'timestamp': datetime.now().isoformat(),
                'source': command.get('source', 'unknown')
            }

    def _extract_result_from_response(self, response: str, command: str) -> Optional[str]:
        """Extract the actual result from vctrold response."""
        if self.debug:
            self.logger.debug(f"Extracting result from response for command {command}")

        if not response or not response.strip():
            if self.debug:
                self.logger.debug("Empty response")
            return None

        lines = response.strip().split('\n')

        if len(lines) == 1:
            line = lines[0].strip()
            if line == 'vctrld>' or line == command:
                if self.debug:
                    self.logger.debug("Only prompt or command echo found")
                return None

            if 'vctrld>' in line:
                result = line.replace('vctrld>', '').strip()
                if result and result != command:
                    if self.debug:
                        self.logger.debug(f"Single line result: {result}")
                    return result

            if self.debug:
                self.logger.debug(f"Single line without clear result: {line}")
            return None

        for i, line in enumerate(lines):
            line = line.strip()

            if not line or line == 'vctrld>' or line == command:
                continue

            cleaned = line.replace('vctrld>', '').strip()

            if cleaned and cleaned != command:
                if self.debug:
                    self.logger.debug(f"Found result in line {i}: {cleaned}")
                return cleaned

        if self.debug:
            self.logger.debug("No result found in response")
        return None

    def test_all_commands(self, delay: float = 0.5) -> List[Dict]:
        """Test all commands with LIVE updating fancy table."""
        total_commands = len(self.commands)

        # Force simple table if simple_mode is enabled
        use_rich = RICH_AVAILABLE and not getattr(self, 'simple_mode', False)

        if use_rich:
            # Create the live results table
            table = Table(title="🔥 vcontrold Tester v1.0.0 | Live Results", box=box.ROUNDED)
            table.add_column("#", style="dim", width=3)
            table.add_column("Command", style="cyan", no_wrap=True)
            table.add_column("Status", justify="center", width=6)
            table.add_column("Result", style="white")
            table.add_column("Description", style="blue")  # ADDED: Description column
            table.add_column("Time", style="yellow", justify="right", width=8)
            table.add_column("Progress", style="green")

            def create_stats_panel():
                total_tested = len(self.results)
                successful = sum(1 for r in self.results if r['status'] == 'SUCCESS')
                errors = sum(1 for r in self.results if r['status'] == 'ERROR')
                no_data = sum(1 for r in self.results if r['status'] == 'NO_DATA')
                conn_errors = sum(1 for r in self.results if r['status'] in ['CONNECTION_ERROR', 'TIMEOUT'])

                stats_text = (
                    f"[green]✅ Success: {successful}[/green]   "
                    f"[yellow]⚠ No Data: {no_data}[/yellow]   "
                    f"[red]❌ Errors: {errors}[/red]   "
                    f"[red]🔌 Conn: {conn_errors}[/red]   "
                    f"[blue]📊 Progress: {total_tested}/{total_commands} ({total_tested/total_commands*100:.1f}%)[/blue]"
                )
                return Panel(stats_text, title="Live Statistics", border_style="blue")

            def update_display():
                # Update table function
                new_table = Table(title="🔥 vcontrold Tester v1.0.0 | Live Results", box=box.ROUNDED)
                new_table.add_column("#", style="dim", width=3)
                new_table.add_column("Command", style="cyan", no_wrap=True)
                new_table.add_column("Status", justify="center", width=6)
                new_table.add_column("Result", style="white")
                new_table.add_column("Description", style="blue")  # ADDED: Description column
                new_table.add_column("Time", style="yellow", justify="right", width=8)
                new_table.add_column("Progress", style="green")

                # Clear and rebuild table
                for i, result in enumerate(self.results, 1):
                    status_style = {
                        'SUCCESS': 'green',
                        'ERROR': 'red',
                        'NO_DATA': 'yellow',
                        'CONNECTION_ERROR': 'red',
                        'TIMEOUT': 'red'
                    }.get(result['status'], 'white')

                    status_icon = {
                        'SUCCESS': '✅',
                        'ERROR': '❌',
                        'NO_DATA': '⚠',
                        'CONNECTION_ERROR': '🔌',
                        'TIMEOUT': '⏰'
                    }.get(result['status'], '❓')

                    progress_bar = '█' * 10  # Full bar for completed

                    # Truncate long descriptions
                    description = result.get('description', 'N/A')
                    if len(description) > 60:
                        description = description[:60] + "..."

                    new_table.add_row(
                        str(i),
                        (result['command'][:35] + "...") if len(result['command']) > 35 else result['command'],
                        f"[{status_style}]{status_icon}[/{status_style}]",
                        (result['result'][:60] + "...") if len(result['result']) > 60 else result['result'],
                        description,  # ADDED: Description value
                        f"{result['execution_time']:.3f}s",
                        f"[green]{progress_bar}[/green]"
                    )

                # Add current command being tested (if any)
                current_index = len(self.results)
                if current_index < total_commands:
                    current_cmd = self.commands[current_index]
                    progress_bar = '█' * 5 + '░' * 5  # Half-filled bar

                    # Truncate long descriptions
                    description = current_cmd.get('description', 'N/A')
                    if len(description) > 60:
                        description = description[:60] + "..."

                    new_table.add_row(
                        str(current_index + 1),
                        (current_cmd['name'][:35] + "...") if len(current_cmd['name']) > 35 else current_cmd['name'],
                        "[yellow]⚙[/yellow]",
                        "[dim]Testing...[/dim]",
                        description,  # ADDED: Description value
                        "[dim]...[/dim]",
                        f"[yellow]{progress_bar}[/yellow]"
                    )

                # Add remaining commands (preview next 10)
                for i in range(current_index + 1, min(current_index + 10, total_commands)):
                    cmd = self.commands[i]
                    progress_bar = '░' * 10  # Empty bar

                    # Truncate long descriptions
                    description = cmd.get('description', 'N/A')
                    if len(description) > 60:
                        description = description[:60] + "..."

                    new_table.add_row(
                        str(i + 1),
                        (cmd['name'][:35] + "...") if len(cmd['name']) > 35 else cmd['name'],
                        "[dim]⋯[/dim]",
                        "[dim]Waiting...[/dim]",
                        description,  # ADDED: Description value
                        "[dim]...[/dim]",
                        f"[dim]{progress_bar}[/dim]"
                    )

                if total_commands - current_index > 10:
                    new_table.add_row(
                        "...",
                        "...",
                        "...",
                        f"[dim]... and {total_commands - current_index - 10} more[/dim]",
                        "...",  # ADDED: Description ellipsis
                        "...",
                        "..."
                    )

                # Combine stats and table
                layout = Layout()
                layout.split_column(
                    Layout(create_stats_panel(), size=3),
                    Layout(new_table)
                )
                return layout

            # Live display
            with Live(update_display(), refresh_per_second=2, console=self.console) as live:
                for i, command in enumerate(self.commands, 1):
                    if self.debug:
                        self.console.print(f"[DEBUG] Starting command {i}/{total_commands}: {command['name']}", style="dim")

                    live.update(update_display())  # Update display to show current command

                    result = self.execute_command(command)
                    self.results.append(result)

                    if self.debug:
                        debug_text = f"[DEBUG] Completed {command['name']}: {result['status']} - {result['result'][:50]}"
                        self.console.print(debug_text, style="dim")

                    live.update(update_display())  # Update display with new result

                    if delay > 0 and i < total_commands:
                        time.sleep(delay)

                live.update(update_display())  # Final update

        else:
            # Fallback without Rich - simple table
            print(f"\nTesting {total_commands} commands...")
            print("-" * 150)
            print(f"{'#':>3} {'Command':<35} {'Status':<12} {'Result':<60} {'Description':<60} {'Time':>8}")
            print("-" * 150)

            for i, command in enumerate(self.commands, 1):
                desc_short = command.get('description', 'N/A')
                if len(desc_short) > 60:
                    desc_short = desc_short[:60] + "..."

                print(f"{i:>3} {command['name']:<35} {'Testing...':<12} {'...':<60} {desc_short:<60} {'...':>8}", end='\r')
                result = self.execute_command(command)
                self.results.append(result)

                status_icon = {
                    'SUCCESS': '✅',
                    'ERROR': '❌',
                    'NO_DATA': '⚠',
                    'CONNECTION_ERROR': '🔌',
                    'TIMEOUT': '⏰'
                }.get(result['status'], '❓')

                # Truncate command name to match Rich table width
                cmd_short = command['name']
                if len(cmd_short) > 35:
                    cmd_short = cmd_short[:32] + "..."

                # Truncate result to match Rich table width
                result_short = result['result']
                if len(result_short) > 60:
                    result_short = result_short[:60] + "..."

                # Truncate description to match Rich table width
                desc_short = result.get('description', 'N/A')
                if len(desc_short) > 60:
                    desc_short = desc_short[:60] + "..."

                print(f"{i:>3} {cmd_short:<35} {status_icon} {result['status']:<12} {result_short:<60} {desc_short:<60} {result['execution_time']:>6.3f}s")

                if delay > 0 and i < total_commands:
                    time.sleep(delay)

        return self.results

    def save_results(self, filename: Optional[str] = None) -> str:
        """Save results to CSV file."""
        if filename is None:
            filename = f"vcontrold_tester_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        fieldnames = ['command', 'address', 'length', 'unit', 'description',
                     'status', 'result', 'execution_time', 'timestamp', 'source']

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.results)

        return filename

    def save_json_results(self, filename: Optional[str] = None) -> str:
        """Save results to JSON file."""
        if filename is None:
            filename = f"vcontrold_tester_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump(self.results, jsonfile, indent=2, ensure_ascii=False)

        return filename

    def save_html_results(self, filename: Optional[str] = None) -> str:
        """Save beautiful HTML report."""
        if filename is None:
            filename = f"vcontrold_tester_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

        # Calculate statistics
        total = len(self.results)
        successful = sum(1 for r in self.results if r['status'] == 'SUCCESS')
        errors = sum(1 for r in self.results if r['status'] == 'ERROR')
        no_data = sum(1 for r in self.results if r['status'] == 'NO_DATA')
        conn_errors = sum(1 for r in self.results if r['status'] == 'CONNECTION_ERROR')

        avg_time = sum(r['execution_time'] for r in self.results) / total if total > 0 else 0

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>vcontrold Tester v1.0.0 Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}

        .container {{
            max-width: 2200px;
            margin: 0 auto;
            padding: 20px;
        }}

        .header {{
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            text-align: center;
        }}

        .header h1 {{
            color: #2c3e50;
            font-size: 2.5em;
            margin-bottom: 10px;
            background: linear-gradient(45deg, #3498db, #2ecc71);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        .header .subtitle {{
            color: #7f8c8d;
            font-size: 1.2em;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.3s ease;
        }}

        .stat-card:hover {{
            transform: translateY(-5px);
        }}

        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 10px;
        }}

        .stat-label {{
            color: #7f8c8d;
            font-size: 1.1em;
        }}

        .success {{ color: #27ae60; }}
        .error {{ color: #e74c3c; }}
        .warning {{ color: #f39c12; }}
        .info {{ color: #3498db; }}

        .results-section {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}

        .section-title {{
            font-size: 1.8em;
            color: #2c3e50;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #3498db;
        }}

        .table-container {{
            overflow-x: auto;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}

        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ecf0f1;
        }}

        th {{
            background: linear-gradient(135deg, #3498db, #2ecc71);
            color: white;
            font-weight: 600;
            position: sticky;
            top: 0;
            z-index: 10;
        }}

        tr:nth-child(even) {{
            background: #f8f9fa;
        }}

        tr:hover {{
            background: #e3f2fd;
            transition: background 0.3s ease;
        }}

        .status-badge {{
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
            text-transform: uppercase;
        }}

        .status-success {{
            background: #d4edda;
            color: #155724;
        }}

        .status-error {{
            background: #f8d7da;
            color: #721c24;
        }}

        .status-no-data {{
            background: #fff3cd;
            color: #856404;
        }}

        .status-conn-error {{
            background: #f5c6cb;
            color: #721c24;
        }}

        .command-name {{
            font-family: 'Courier New', monospace;
            background: #f1f2f6;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
        }}

        .result-value {{
            font-family: 'Courier New', monospace;
            font-weight: bold;
        }}

        .execution-time {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}

        .footer {{
            text-align: center;
            color: white;
            margin-top: 30px;
            opacity: 0.8;
        }}

        .progress-bar {{
            background: #ecf0f1;
            height: 20px;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }}

        .progress-fill {{
            height: 100%;
            border-radius: 10px;
            transition: width 0.3s ease;
        }}

        .success-bar {{ background: linear-gradient(45deg, #2ecc71, #27ae60); }}
        .error-bar {{ background: linear-gradient(45deg, #e74c3c, #c0392b); }}
        .warning-bar {{ background: linear-gradient(45deg, #f39c12, #e67e22); }}

        @media (max-width: 768px) {{
            .container {{
                padding: 10px;
            }}

            .header h1 {{
                font-size: 2em;
            }}

            .stats-grid {{
                grid-template-columns: 1fr;
            }}

            table {{
                font-size: 0.9em;
            }}

            th, td {{
                padding: 8px;
            }}
        }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔥 vcontrold Tester v1.0.0 Results</h1>
            <div class="subtitle">Viessmann Heating System Command Analysis</div>
            <div class="subtitle">Generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}</div>
            <div class="subtitle">Host: {self.host}:{self.port} | Smart Timeout: {self.timeout}s</div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number success">{successful}</div>
                <div class="stat-label">Successful Commands</div>
                <div class="progress-bar">
                    <div class="progress-fill success-bar" style="width: {successful/total*100 if total > 0 else 0:.1f}%"></div>
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-number error">{errors + conn_errors}</div>
                <div class="stat-label">Failed Commands</div>
                <div class="progress-bar">
                    <div class="progress-fill error-bar" style="width: {(errors + conn_errors)/total*100 if total > 0 else 0:.1f}%"></div>
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-number warning">{no_data}</div>
                <div class="stat-label">No Data Returned</div>
                <div class="progress-bar">
                    <div class="progress-fill warning-bar" style="width: {no_data/total*100 if total > 0 else 0:.1f}%"></div>
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-number info">{total}</div>
                <div class="stat-label">Total Commands</div>
                <div class="progress-bar">
                    <div class="progress-fill info" style="width: 100%; background: linear-gradient(45deg, #3498db, #2980b9);"></div>
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-number info">{avg_time:.3f}s</div>
                <div class="stat-label">Average Response Time</div>
            </div>

            <div class="stat-card">
                <div class="stat-number success">{successful/total*100 if total > 0 else 0:.1f}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
        </div>

        <div class="results-section">
            <h2 class="section-title">📊 Detailed Results</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Command</th>
                            <th>Status</th>
                            <th>Result</th>
                            <th>Description</th>
                            <th>Address</th>
                            <th>Unit</th>
                            <th>Response Time</th>
                            <th>Source</th>
                        </tr>
                    </thead>
                    <tbody>
"""

        # Add table rows
        for i, result in enumerate(self.results, 1):
            status_class = {
                'SUCCESS': 'status-success',
                'ERROR': 'status-error',
                'NO_DATA': 'status-no-data',
                'CONNECTION_ERROR': 'status-conn-error'
            }.get(result['status'], 'status-no-data')

            status_icon = {
                'SUCCESS': '✅',
                'ERROR': '❌',
                'NO_DATA': '⚠️',
                'CONNECTION_ERROR': '🔌'
            }.get(result['status'], '❓')

            html_content += f"""
                        <tr>
                            <td>{i}</td>
                            <td><span class="command-name">{result['command']}</span></td>
                            <td><span class="status-badge {status_class}">{status_icon} {result['status']}</span></td>
                            <td><span class="result-value">{result['result']}</span></td>
                            <td>{result['description']}</td>
                            <td><code>{result['address']}</code></td>
                            <td><code>{result['unit']}</code></td>
                            <td><span class="execution-time">{result['execution_time']}s</span></td>
                            <td>{result['source']}</td>
                        </tr>
"""

        html_content += f"""
                    </tbody>
                </table>
            </div>
        </div>

        <div class="results-section">
            <h2 class="section-title">📈 Success Rate Analysis</h2>
            <div style="text-align: center;">
                <canvas id="categoryChart" width="400" height="200"></canvas>
            </div>
        </div>

        <div class="footer">
            <p>Generated by vcontrold Tester v1.0.0</p>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('categoryChart').getContext('2d');
        const categoryChart = new Chart(ctx, {{
            type: 'doughnut',
            data: {{
                labels: ['Successful', 'Errors', 'No Data', 'Connection Errors'],
                datasets: [{{
                    data: [{successful}, {errors}, {no_data}, {conn_errors}],
                    backgroundColor: [
                        '#2ecc71',
                        '#e74c3c',
                        '#f39c12',
                        '#95a5a6'
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{
                            padding: 20,
                            font: {{
                                size: 14
                            }}
                        }}
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                const total = {total};
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return filename

    def print_beautiful_summary(self):
        """Print beautiful final summary."""
        if not self.results:
            if RICH_AVAILABLE:
                self.console.print("⚠️ No results to display", style="yellow")
            else:
                print("⚠️ No results to display")
            return

        total = len(self.results)
        successful = sum(1 for r in self.results if r['status'] == 'SUCCESS')
        errors = sum(1 for r in self.results if r['status'] == 'ERROR')
        no_data = sum(1 for r in self.results if r['status'] == 'NO_DATA')
        conn_errors = sum(1 for r in self.results if r['status'] == 'CONNECTION_ERROR')
        avg_time = sum(r['execution_time'] for r in self.results) / total if total > 0 else 0

        if RICH_AVAILABLE:
            # Create final summary table
            summary_table = Table(title="📊 Final Test Summary", box=box.ROUNDED)
            summary_table.add_column("Metric", style="cyan", no_wrap=True)
            summary_table.add_column("Count", style="white", justify="right")
            summary_table.add_column("Percentage", style="yellow", justify="right")

            summary_table.add_row("Total Commands", str(total), "100.0%")
            summary_table.add_row("✅ Successful", str(successful), f"{successful/total*100:.1f}%")
            summary_table.add_row("⚠️ No Data", str(no_data), f"{no_data/total*100:.1f}%")
            summary_table.add_row("❌ Errors", str(errors), f"{errors/total*100:.1f}%")
            summary_table.add_row("🔌 Connection Errors", str(conn_errors), f"{conn_errors/total*100:.1f}%")
            summary_table.add_row("⏱️ Avg Response Time", f"{avg_time:.3f}s", "-")

            self.console.print()
            self.console.print(Panel(summary_table, title="🎉 Test Completed Successfully!", border_style="green"))

            # Show top successful commands
            if successful > 0:
                success_table = Table(title="🏆 Top Successful Commands", box=box.ROUNDED)
                success_table.add_column("Command", style="cyan")
                success_table.add_column("Result", style="green")
                success_table.add_column("Response Time", style="yellow", justify="right")

                success_results = [r for r in self.results if r['status'] == 'SUCCESS']
                for result in success_results[:10]:  # Top 10
                    success_table.add_row(
                        result['command'],
                        result['result'][:40] + ("..." if len(result['result']) > 40 else ""),
                        f"{result['execution_time']:.3f}s"
                    )

                self.console.print()
                self.console.print(success_table)
        else:
            # Fallback ASCII
            print("\n" + "="*80)
            print("🎉 FINAL TEST SUMMARY")
            print("="*80)
            print(f"Total commands tested: {total}")
            print(f"✅ Successful:         {successful:3d} ({successful/total*100:.1f}%)")
            print(f"⚠️ No data:           {no_data:3d} ({no_data/total*100:.1f}%)")
            print(f"❌ Errors:            {errors:3d} ({errors/total*100:.1f}%)")
            print(f"🔌 Connection errors:  {conn_errors:3d} ({conn_errors/total*100:.1f}%)")
            print(f"⏱️ Average response time: {avg_time:.3f}s")
            print("="*80)

    def list_discovered_commands(self):
        """List all discovered commands beautifully."""
        if RICH_AVAILABLE:
            table = Table(title="🔍 Discovered Commands", box=box.ROUNDED)
            table.add_column("#", style="dim", width=4)
            table.add_column("Command", style="cyan", no_wrap=True)
            table.add_column("Address", style="yellow", justify="center")
            table.add_column("Length", style="magenta", justify="center")
            table.add_column("Unit", style="green", justify="center")
            table.add_column("Description", style="white")
            table.add_column("Source", style="dim")

            for i, cmd in enumerate(self.commands, 1):
                table.add_row(
                    str(i),
                    cmd['name'],
                    cmd.get('addr', 'N/A'),
                    cmd.get('len', 'N/A'),
                    cmd.get('unit', 'N/A'),
                    cmd.get('description', 'N/A')[:60] + ("..." if len(cmd.get('description', '')) > 60 else ""),
                    cmd.get('source', 'unknown')
                )

            self.console.print()
            self.console.print(table)
            self.console.print(f"\n✨ Total: [green]{len(self.commands)}[/green] GET commands discovered", style="bold")
        else:
            print("\n🔍 DISCOVERED COMMANDS:")
            print("="*100)
            for i, cmd in enumerate(self.commands, 1):
                print(f"{i:3d}. {cmd['name']:<35} | addr: {cmd.get('addr', 'N/A'):<6} | "
                      f"len: {cmd.get('len', 'N/A'):<3} | unit: {cmd.get('unit', 'N/A'):<6} | "
                      f"{cmd.get('description', 'N/A')}")
            print(f"\n✨ Total: {len(self.commands)} GET commands discovered")

def main():
    parser = argparse.ArgumentParser(description='🔥 vcontrold Tester v1.0.0')
    parser.add_argument('--host', default='127.0.0.1', help='vcontrold host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=3002, help='vcontrold port (default: 3002)')
    parser.add_argument('--timeout', type=int, default=30, help='Smart timeout in seconds (default: 30)')
    parser.add_argument('--delay', type=float, default=0, help='Delay between commands in seconds (default: 0)')
    parser.add_argument('--output', help='Output CSV filename (default: auto-generate)')
    parser.add_argument('--html', help='Output HTML filename (default: auto-generate)')
    parser.add_argument('--json', help='Output JSON filename (Enable JSON file generation) (default: disabled)')
    parser.add_argument('--no-summary', action='store_true', help='Skip printing final summary')
    parser.add_argument('--list-commands', action='store_true', help='List discovered commands and exit')
    parser.add_argument('--vito-xml', default='vito.xml', help='Path to vito.xml file (default: vito.xml)')
    parser.add_argument('--vcontrold-xml', default='vcontrold.xml', help='Path to vcontrold.xml file (default: vcontrold.xml)')
    parser.add_argument('--test-single', help='Test only a single command (for debugging)')
    parser.add_argument('--simple', action='store_true', help='Use simple ASCII table instead of Rich live table')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode with verbose console output')

    args = parser.parse_args()

    # Create tester instance
    tester = VcontroldTester(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        vito_xml=args.vito_xml,
        vcontrold_xml=args.vcontrold_xml,
        debug=args.debug,
        simple_mode=args.simple  # Pass the --simple flag here
    )

    if args.list_commands:
        tester.list_discovered_commands()
        return 0

    if args.test_single:
        single_cmd = None
        for cmd in tester.commands:
            if cmd['name'] == args.test_single:
                single_cmd = cmd
                break

        if not single_cmd:
            if RICH_AVAILABLE:
                tester.console.print(f"❌ Command '[red]{args.test_single}[/red]' not found!", style="red")
            else:
                print(f"❌ Command '{args.test_single}' not found!")
            return 1

        if RICH_AVAILABLE:
            tester.console.print(f"🧪 Testing single command: [cyan]{args.test_single}[/cyan]")
            if args.debug:
                tester.console.print("🐛 Debug mode enabled - verbose output active", style="yellow")
        else:
            print(f"🧪 Testing single command: {args.test_single}")
            if args.debug:
                print("🐛 Debug mode enabled - verbose output active")

        result = tester.execute_command(single_cmd)

        if RICH_AVAILABLE:
            # Create single result table
            table = Table(title="🎯 Single Command Result", box=box.ROUNDED)
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="white")

            for key, value in result.items():
                table.add_row(key.replace('_', ' ').title(), str(value))

            tester.console.print()
            tester.console.print(table)
        else:
            print(f"\n🎯 Result: {result}")

        return 0

    if not tester.test_connection():
        if RICH_AVAILABLE:
            tester.console.print("❌ Failed to connect to vcontrold daemon. Exiting.", style="red bold")
        else:
            print("❌ Failed to connect to vcontrold daemon. Exiting.")
        return 1

    if RICH_AVAILABLE:
        tester.console.print(f"\n🔍 Discovered [green bold]{len(tester.commands)}[/green bold] GET commands from XML files")

        if args.debug:
            tester.console.print("🐛 Debug mode enabled - verbose console output active", style="yellow bold")

        info_panel = Panel(
            f"[blue]Host:[/blue] {args.host}:{args.port}\n[blue]Smart Timeout:[/blue] {args.timeout}s\n[blue]Delay:[/blue] {args.delay}s",
            title="🚀 Test Configuration",
            border_style="blue"
        )
        tester.console.print(info_panel)
    else:
        print(f"\n🔍 Discovered {len(tester.commands)} GET commands from XML files")
        if args.debug:
            print("🐛 Debug mode enabled - verbose console output active")
        print(f"\n🚀 Test Configuration:")
        print(f"   Host: {args.host}:{args.port}")
        print(f"   Smart Timeout: {args.timeout}s")
        print(f"   Delay: {args.delay}s")

    start_time = time.time()

    # Run the tests with live updates
    results = tester.test_all_commands(args.delay)

    end_time = time.time()

    if RICH_AVAILABLE:
        tester.console.print(f"\n✅ All tests completed in [green bold]{end_time - start_time:.2f}[/green bold] seconds")
    else:
        print(f"\n✅ All tests completed in {end_time - start_time:.2f} seconds")

    # Save results
    csv_file = tester.save_results(args.output)
    html_file = tester.save_html_results(args.html)

    if args.json:
        json_file = tester.save_json_results(args.json)

    # Print beautiful final summary
    if not args.no_summary:
        tester.print_beautiful_summary()

    # Show file outputs
    if RICH_AVAILABLE:
        output_table = Table(title="📁 Generated Files", box=box.ROUNDED)
        output_table.add_column("Format", style="cyan")
        output_table.add_column("Filename", style="green")
        output_table.add_column("Description", style="white")

        output_table.add_row("📊 CSV", csv_file, "Structured data for analysis and import")
        output_table.add_row("🌐 HTML", html_file, "Beautiful web report with interactive charts")

        if args.json:
            output_table.add_row("📋 JSON", json_file, "Machine-readable data in JSON format")

        tester.console.print()
        tester.console.print(output_table)

        tester.console.print(f"\n🌐 Open HTML report: [link]{html_file}[/link]")
        tester.console.print("🎉 vcontrold Tester v1.0.0 completed successfully!", style="green bold")
    else:
        print(f"\n📁 Generated Files:")
        print(f"  📊 CSV:  {csv_file}")
        print(f"  🌐 HTML: {html_file}")
        if args.json:
            print(f"  📋 JSON: {json_file}")
        print("\n🎉 vcontrold Tester v1.0.0 completed successfully!")

    return 0

if __name__ == '__main__':
    exit(main())
