"""CLI commands."""
import json
import sys
from pathlib import Path

import click

from app.excel_export import build_excel_export
from app.input_schema import ProjectInputsSchema
from app.input_adapter import build_projectinputs


@click.group()
def cli():
    """FINCO Model CLI — run project models from the command line."""
    pass


SUPPORTED_PROJECTS = {"Solar", "Wind"}
SUPPORTED_SCENARIOS = {"Base", "Downside", "Upside"}
SUPPORTED_PERIOD_VIEWS = {"Semiannual", "Annual"}


@cli.command()
@click.option('--project', 'project', required=True, type=str,
              help='Solar or Wind')
@click.option('--scenario', required=True, type=str,
              help='Base, Downside, or Upside')
@click.option('--period-view', default='Semiannual', type=str,
              help='Semiannual or Annual')
@click.option('--input', 'input_file', type=click.Path(exists=True),
              help='Custom project JSON file (optional)')
@click.option('--output', default=None, type=str,
              help='Output Excel file path')
@click.option('--json', 'json_output', default=None, type=str,
              help='Output JSON file path')
def run(project, scenario, period_view, input_file, output, json_output):
    """Run a project model and optionally export results."""
    if project not in SUPPORTED_PROJECTS:
        click.echo(f'Error: --project must be one of {SUPPORTED_PROJECTS}', err=True)
        sys.exit(1)
    if scenario not in SUPPORTED_SCENARIOS:
        click.echo(f'Error: --scenario must be one of {SUPPORTED_SCENARIOS}', err=True)
        sys.exit(1)
    if period_view not in SUPPORTED_PERIOD_VIEWS:
        click.echo(f'Error: --period-view must be one of {SUPPORTED_PERIOD_VIEWS}', err=True)
        sys.exit(1)

    project_inputs_override = None
    if input_file:
        try:
            with open(input_file) as f:
                data = json.load(f)
            schema = ProjectInputsSchema(**data)

            if project is not None and schema.project_type != project:
                click.echo(
                    f"ERROR: --project '{project}' does not match "
                    f"inputs project_type '{schema.project_type}'",
                    err=True
                )
                sys.exit(1)

            if scenario is not None and schema.scenario is not None and schema.scenario != scenario:
                click.echo(
                    f"ERROR: --scenario '{scenario}' does not match "
                    f"inputs scenario '{schema.scenario}'",
                    err=True
                )
                sys.exit(1)

            project_inputs_override = build_projectinputs(schema)
            click.echo(f'Loaded custom inputs from {input_file}')
        except Exception as e:
            click.echo(f'Error parsing {input_file}: {e}', err=True)
            sys.exit(1)

    click.echo(f'Running {project} {scenario} ({period_view})...')

    try:
        from app.services.production_waterfall_seam import execute_production_demo
        demo, _authority_meta = execute_production_demo(
            project, scenario, project_inputs_override=project_inputs_override)
        result = demo.result
        proj_inputs = getattr(demo, 'project_inputs', None)

        if json_output:
            kpis = {
                'project_irr': result.project_irr,
                'equity_irr': result.equity_irr,
                'actual_min_dscr': result.actual_min_dscr,
                'actual_avg_dscr': result.actual_avg_dscr,
                'total_revenue_keur': result.total_revenue_keur,
                'total_ebitda_keur': result.total_ebitda_keur,
            }
            with open(json_output, 'w') as f:
                json.dump(kpis, f, indent=2)
            click.echo(f'JSON output: {json_output}')

        if output:
            excel_bytes = build_excel_export(
                result=result,
                scenario=scenario,
                project_type=project,
                period_view=period_view,
                advanced_opex_line_items=None,
                advanced_capex_line_items=None,
                warnings=[{"code": "INFO", "message": msg} for msg in demo.messages]
                if getattr(demo, 'messages', None) else None,
                validation_issues=getattr(demo, 'validation_issues', None),
                project_inputs=proj_inputs,
                integration_status=getattr(demo, 'integration_status', 'full'),
                integration_note=getattr(demo, 'integration_note', None),
            )
            with open(output, 'wb') as f:
                f.write(excel_bytes)
            click.echo(f'Excel output: {output}')

        click.echo(f'Success: IRR={result.project_irr*100:.2f}%, minDSCR={result.actual_min_dscr:.3f}x')

    except Exception as e:
        click.echo(f'Error: {e}', err=True)
        sys.exit(1)


@cli.command(name='batch')
@click.option('--input', 'input_path', required=True, type=click.Path(exists=True),
              help='JSON batch input file')
@click.option('--output', 'output_path', default=None, type=str,
              help='JSON output file (optional)')
@click.option('--fail-fast', is_flag=True,
              help='Stop on first error')
def batch(input_path, output_path, fail_fast):
    """Run a batch of project configurations from a JSON file."""
    with open(input_path) as f:
        projects = json.load(f)

    if not isinstance(projects, list):
        click.echo('Error: batch JSON must be a list of project objects', err=True)
        sys.exit(1)

    results = []
    for i, proj_def in enumerate(projects):
        pt = proj_def.get('project_type')
        sc = proj_def.get('scenario', 'Base')
        pv = proj_def.get('period_view', 'Semiannual')
        inputs_dict = proj_def.get('inputs')

        if pt not in SUPPORTED_PROJECTS:
            msg = f'Row {i}: unsupported project_type "{pt}"'
            if fail_fast:
                raise ValueError(msg)
            results.append({'index': i, 'status': 'failed', 'project_type': pt, 'scenario': sc, 'error': msg})
            continue

        try:
            project_inputs_override = None
            if inputs_dict:
                schema = ProjectInputsSchema(**inputs_dict)
                if schema.project_type and schema.project_type != pt:
                    raise ValueError(f"inputs project_type '{schema.project_type}' != '{pt}'")
                project_inputs_override = build_projectinputs(schema)

            # Use same run_demo_project approach as CLI `run` command
            from app.services.production_waterfall_seam import execute_production_demo
            demo, _authority_meta = execute_production_demo(
                pt, sc, project_inputs_override=project_inputs_override)
            result = demo.result
            kpis = {
                'project_irr': result.project_irr,
                'equity_irr': result.equity_irr,
                'actual_min_dscr': result.actual_min_dscr,
                'actual_avg_dscr': result.actual_avg_dscr,
                'total_revenue_keur': result.total_revenue_keur,
            }
            results.append({
                'index': i,
                'status': 'success',
                'project_type': pt,
                'scenario': sc,
                'period_view': pv,
                'project_irr': kpis['project_irr'],
                'equity_irr': kpis['equity_irr'],
                'min_dscr': kpis['actual_min_dscr'],
                'avg_dscr': kpis['actual_avg_dscr'],
                'total_revenue_keur': kpis['total_revenue_keur'],
            })
        except Exception as e:
            if fail_fast:
                raise
            results.append({
                'index': i,
                'status': 'failed',
                'project_type': pt,
                'scenario': sc,
                'error': str(e),
            })

    for r in results:
        status = r['status']
        pt = r.get('project_type', '?')
        sc = r.get('scenario', '?')
        if status == 'success':
            irr = f"{r.get('project_irr', 0)*100:.2f}%" if r.get('project_irr') is not None else 'N/A'
            click.echo(f"  [{r['index']}] {pt}/{sc} → IRR={irr} OK")
        else:
            click.echo(f"  [{r['index']}] {pt}/{sc} → FAILED: {r.get('error', 'unknown')}")

    if output_path:
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)

    total = len(results)
    succeeded = sum(1 for r in results if r['status'] == 'success')
    failed = total - succeeded
    click.echo(f"\nBatch complete: {succeeded}/{total} succeeded")
    if failed > 0:
        click.echo(f"  {failed} failed (use --fail-fast to stop on first error)")
        sys.exit(1)


if __name__ == '__main__':
    cli()
