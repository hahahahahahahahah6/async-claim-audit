"""Command line interface."""
import argparse
import json
import sys
from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(prog='async-claim-audit', description='Audit documented awaitability promises against static Python evidence.')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB')
    parser.add_argument('--fail-on', choices=('MEDIUM', 'HIGH'), default='MEDIUM')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.path, args.ignore)
    except (OSError, ValueError, UnicodeError) as exc:
        parser.exit(1, str(exc) + '\n')
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for finding in result['findings']:
            print(f"{finding['severity']} {finding['rule']}")
            for claim in finding['claims']:
                print(f"  {claim['path']}: {claim['sentence']}")
            if args.verbose:
                for evidence in finding['evidence']:
                    print('  ' + json.dumps(evidence))
        for error in result['errors']:
            print('Parse error: ' + error['path'] + ': ' + error['error'], file=sys.stderr)
        if not result['findings']:
            print('PASS')
        if args.verbose:
            print(f"Verified families: {len(result['verified_claims'])}")
    if result['errors']:
        return 1
    return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings']) else 0


if __name__ == '__main__':
    sys.exit(main())
