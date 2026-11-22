import 'package:cocauto/src/release_checker.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('detects a higher rc build', () {
    expect(
      compareReleaseVersions('v2026.11.19-rc117', 'v2026.11.19-rc116'),
      greaterThan(0),
    );
    expect(
      compareReleaseVersions('v2026.11.19-rc116', 'v2026.11.18-rc110'),
      greaterThan(0),
    );
  });

  test('does not treat the same or older build as an update', () {
    expect(compareReleaseVersions('v2026.11.19-rc116', 'v2026.11.19-rc116'), 0);
    expect(
      compareReleaseVersions('v2026.11.18-rc110', 'v2026.11.19-rc116'),
      lessThan(0),
    );
  });

  test('compares numeric version components and ignores build metadata', () {
    expect(compareReleaseVersions('v1.4.0', '1.3.9+7'), greaterThan(0));
    expect(compareReleaseVersions('1.2.0+9', '1.2.0+4'), 0);
  });

  test('a stable release outranks a prerelease with the same core version', () {
    expect(
      compareReleaseVersions('v2026.11.19', 'v2026.11.19-rc116'),
      greaterThan(0),
    );
    expect(
      compareReleaseVersions('v2026.11.19-rc116', 'v2026.11.19'),
      lessThan(0),
    );
    expect(
      compareReleaseVersions('v2026.11.19-rc1000', 'v2026.11.19-rc999'),
      greaterThan(0),
    );
  });

  test('offers the final release when installed on the matching rc', () {
    final release = parseLatestRelease({
      'tag_name': 'v2026.11.19',
      'html_url':
          'https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19',
      'body': '正式版',
      'draft': false,
      'prerelease': false,
    }, currentVersion: 'v2026.11.19-rc116');

    expect(release?.version, 'v2026.11.19');
  });

  test('parses only a newer release from the configured GitHub repository', () {
    final release = parseLatestRelease([
      {
        'tag_name': 'v2026.11.19-rc115',
        'html_url': 'https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc115',
        'body': '旧测试包。',
        'draft': false,
        'prerelease': true,
      },
      {
        'tag_name': 'v2026.11.19-rc117',
        'html_url': 'https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc117',
        'body': '修复连接恢复。',
        'draft': false,
        'prerelease': true,
      },
    ], currentVersion: 'v2026.11.19-rc116');

    expect(release?.version, 'v2026.11.19-rc117');
    expect(release?.notes, '修复连接恢复。');
    expect(release?.page.host, 'github.com');
  });

  test('ignores same and older releases but accepts published previews', () {
    final release = <String, Object?>{
      'tag_name': 'v2026.11.19-rc116',
      'html_url':
          'https://github.com/xiang0825/COCauto/releases/tag/v2026.11.19-rc116',
      'body': '',
      'draft': false,
      'prerelease': true,
    };
    expect(
      parseLatestRelease(release, currentVersion: 'v2026.11.19-rc116'),
      isNull,
    );
    expect(
      parseLatestRelease([
        {...release, 'draft': true, 'tag_name': 'v2026.11.20-rc117'},
      ], currentVersion: 'v2026.11.19-rc116'),
      isNull,
    );
  });

  test('rejects a release URL outside the official repository', () {
    expect(
      () => parseLatestRelease({
        'tag_name': 'v2026.11.20-rc117',
        'html_url': 'https://evil.example/releases/tag/v2026.11.20-rc117',
        'body': '',
        'draft': false,
        'prerelease': false,
      }, currentVersion: 'v2026.11.19-rc116'),
      throwsFormatException,
    );
  });
}
