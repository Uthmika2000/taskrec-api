const express = require('express');
const router = express.Router();
const metricsController = require('../controllers/metricsController');
const { authMiddleware } = require('../middleware/authMiddleware');

router.get('/workload/:sprintId', authMiddleware, metricsController.getWorkload);
router.get('/accuracy',          authMiddleware, metricsController.getAccuracy);
router.get('/evaluation',        authMiddleware, metricsController.getEvaluation);

module.exports = router;
