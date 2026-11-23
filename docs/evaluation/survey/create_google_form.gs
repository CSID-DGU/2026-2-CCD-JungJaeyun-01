/**
 * 밋픽 가중치 설문을 구글폼으로 한 번에 만든다.
 *
 * 사용법 (2분)
 *  1) https://script.google.com 에서 [새 프로젝트]를 만들고 이 파일 내용을 전부 붙여넣는다.
 *  2) 위쪽 함수 선택에서 createSurvey 를 고르고 [실행]을 누른다. (처음에는 구글 계정 권한 허용이 필요하다)
 *  3) 아래쪽 [실행 로그]에 나오는 "응답자에게 보낼 링크"를 응답자에게 보낸다.
 *     응답은 같은 로그에 나오는 구글 시트에 자동으로 쌓인다.
 *  4) 응답이 모이면 시트에서 [파일 → 다운로드 → CSV]로 받아서
 *       python scripts/survey_to_csv.py 받은파일.csv -o 응답.csv
 *       python scripts/analyze_survey.py 응답.csv
 *     를 실행한다.
 *
 * 주의: 문항 앞의 [B1] 같은 표시와 선택지 문구는 backend/scripts/survey_to_csv.py가 응답을 읽는 기준이다.
 *       문구를 바꾸면 변환기(PAIRS, 선택지 문구)도 함께 바꿔야 한다. (tests/test_survey_script.py가 두 파일이 맞는지 검사한다)
 */

var AGES = ['10대', '20대', '30대', '40대', '50대 이상'];

function createSurvey() {
  var form = FormApp.create('밋픽 설문: 약속 장소를 추천할 때 무엇이 더 중요한가요?');
  form.setDescription(
    '친구들과 만날 장소를 추천해 주는 서비스(밋픽)의 점수 기준을 정하려고 해요.\n' +
    '정답은 없고, 느낌대로 골라 주세요. 약 3~5분이 걸리고 이름·위치는 받지 않아요(익명).');
  form.setConfirmationMessage('응답해 주셔서 고마워요!');
  form.setShowLinkToRespondAgain(false);
  form.setProgressBar(true);
  try { form.setCollectEmail(false); } catch (e) {}

  // ---- 1. 이동시간 기준 두 개씩 비교 ----
  form.addPageBreakItem()
    .setTitle('1. 이동시간, 무엇을 더 따질까요?')
    .setHelpText(
      '세 명이 한 장소에서 만난다고 해요. 숫자는 각자 걸리는 이동시간이에요.\n\n' +
      '장소 X: 사람 1은 10분, 사람 2는 10분, 사람 3은 50분 → 평균 23분, 최대 50분\n' +
      '장소 Y: 사람 1은 28분, 사람 2는 30분, 사람 3은 32분 → 평균 30분, 최대 32분\n\n' +
      '· 평균 이동시간: 모두의 이동시간 평균\n' +
      '· 최대 이동시간: 가장 오래 걸리는 사람의 시간\n' +
      '· 이동시간 편차: 사람마다 걸리는 시간이 얼마나 다른가 (작을수록 공평)');
  addPair(form, 'B1', '평균 이동시간', '이', '최대 이동시간', '이');
  addPair(form, 'B2', '평균 이동시간', '이', '이동시간 편차', '가');
  addPair(form, 'B3', '최대 이동시간', '이', '이동시간 편차', '가');

  // ---- 2. 이동시간 기준 중요도 ----
  form.addPageBreakItem()
    .setTitle('2. 이동시간 기준은 얼마나 중요한가요?')
    .setHelpText('0점은 전혀 중요하지 않다, 10점은 매우 중요하다는 뜻이에요. 세 가지 점수의 합을 맞출 필요는 없어요.');
  addScale(form, 'C1', '평균 이동시간은 얼마나 중요한가요?');
  addScale(form, 'C2', '최대 이동시간(가장 오래 걸리는 사람)은 얼마나 중요한가요?');
  addScale(form, 'C3', '이동시간 편차(사람마다 시간이 비슷한 정도)는 얼마나 중요한가요?');

  // ---- 3. 장소 고를 때 ----
  form.addPageBreakItem()
    .setTitle('3. 식당·카페를 고를 때')
    .setHelpText('각 항목이 얼마나 중요한지 0~10점으로 알려 주세요.');
  addScale(form, 'D1', '역에서 가까운 정도는 얼마나 중요한가요?');
  addScale(form, 'D2', '평점은 얼마나 중요한가요?');
  addScale(form, 'D3', '리뷰가 많은 정도는 얼마나 중요한가요?');
  addScale(form, 'D4', '모임 목적에 맞는 종류(예: 식사 모임이면 음식점)는 얼마나 중요한가요?');
  addScale(form, 'D5', '우리 연령대가 좋아하는 종류는 얼마나 중요한가요?');

  // ---- 4. 이런 경우엔? ----
  form.addPageBreakItem()
    .setTitle('4. 이런 경우엔?')
    .setHelpText('장소 P: 사람 1은 15분, 사람 2는 15분, 사람 3은 45분\n장소 Q: 사람 1은 28분, 사람 2는 30분, 사람 3은 32분');
  form.addMultipleChoiceItem()
    .setTitle('[E1] 세 사람이 만난다면 어디로 가겠어요?')
    .setChoiceValues(['장소 P (평균은 짧지만 한 명이 오래 걸려요)', '장소 Q (조금 길어도 모두 비슷해요)'])
    .setRequired(true);
  form.addMultipleChoiceItem()
    .setTitle('[F2] 장소가 훨씬 좋다면, 이동이 몇 분까지 더 걸려도 괜찮나요?')
    .setChoiceValues(['안 괜찮아요(0분)', '5분', '10분', '15분', '20분 이상'])
    .setRequired(true);

  // ---- 마지막 (선택) ----
  form.addPageBreakItem().setTitle('마지막으로 (선택)');
  form.addMultipleChoiceItem().setTitle('[A1] 연령대').setChoiceValues(AGES).setRequired(false);
  form.addParagraphTextItem().setTitle('[Z1] 하고 싶은 말').setRequired(false);

  // ---- 응답을 쌓을 구글 시트 ----
  var sheet = SpreadsheetApp.create('밋픽 설문 응답');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());

  Logger.log('응답자에게 보낼 링크: ' + form.getPublishedUrl());
  Logger.log('폼 수정 화면(본인용): ' + form.getEditUrl());
  Logger.log('응답이 쌓이는 시트(본인용): ' + sheet.getUrl());
}

/** 두 기준 중 어느 쪽이 더 중요한지 묻는 문항. 선택지는 순서대로 7배/3배/같음/1/3/1/7 (변환기가 같은 문구를 읽는다) */
function addPair(form, id, a, josaA, b, josaB) {
  form.addMultipleChoiceItem()
    .setTitle('[' + id + '] ' + a + '과(와) ' + b + ', 어느 쪽이 더 중요한가요?')
    .setChoiceValues([
      a + josaA + ' 훨씬 더 중요해요',
      a + josaA + ' 조금 더 중요해요',
      '둘은 비슷하게 중요해요',
      b + josaB + ' 조금 더 중요해요',0
      b + josaB + ' 훨씬 더 중요해요'
    ])
    .setRequired(true);
}

function addScale(form, id, title) {
  form.addScaleItem()
    .setTitle('[' + id + '] ' + title)
    .setBounds(0, 10)
    .setLabels('전혀 중요하지 않아요', '매우 중요해요')
    .setRequired(true);
}
